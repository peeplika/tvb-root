# -*- coding: utf-8 -*-
#
#
# TheVirtualBrain-Framework Package. This package holds all Data Management, and
# Web-UI helpful to run brain-simulations. To use it, you also need do download
# TheVirtualBrain-Scientific Package (for simulators). See content of the
# documentation-folder for more details. See also http://www.thevirtualbrain.org
#
# (c) 2012-2020, Baycrest Centre for Geriatric Care ("Baycrest") and others
#
# This program is free software: you can redistribute it and/or modify it under the
# terms of the GNU General Public License as published by the Free Software Foundation,
# either version 3 of the License, or (at your option) any later version.
# This program is distributed in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A
# PARTICULAR PURPOSE.  See the GNU General Public License for more details.
# You should have received a copy of the GNU General Public License along with this
# program.  If not, see <http://www.gnu.org/licenses/>.
#
#
#   CITATION:
# When using The Virtual Brain for scientific publications, please cite it as follows:
#
#   Paula Sanz Leon, Stuart A. Knock, M. Marmaduke Woodman, Lia Domide,
#   Jochen Mersmann, Anthony R. McIntosh, Viktor Jirsa (2013)
#       The Virtual Brain: a simulator of primate brain network dynamics.
#   Frontiers in Neuroinformatics (7:10. doi: 10.3389/fninf.2013.00010)
#
#

"""
.. moduleauthor:: Paula Popa <paula.popa@codemart.ro>
"""

import copy
import json
import os
import shutil
import uuid

import numpy
from tvb.basic.logger.builder import get_logger
from tvb.core.entities.file.files_helper import FilesHelper
from tvb.core.entities.file.simulator.view_model import SimulatorAdapterModel
from tvb.core.entities.model.model_datatype import DataTypeGroup
from tvb.core.entities.model.model_operation import Operation
from tvb.core.entities.storage import dao, transactional
from tvb.core.entities.transient.structure_entities import DataTypeMetaData
from tvb.core.neocom import h5
from tvb.core.neocom.h5 import DirLoader
from tvb.core.services.burst_service import BurstService
from tvb.core.services.import_service import ImportService
from tvb.core.services.operation_service import OperationService
from tvb.simulator.integrators import IntegratorStochastic


class SimulatorService(object):
    def __init__(self):
        self.logger = get_logger(self.__class__.__module__)
        self.burst_service = BurstService()
        self.operation_service = OperationService()
        self.files_helper = FilesHelper()

    @staticmethod
    def get_variables_of_interest_indexes(all_variables, chosen_variables):
        indexes = {}

        if not isinstance(chosen_variables, (list, tuple)):
            chosen_variables = [chosen_variables]

        for variable in chosen_variables:
            indexes[variable] = all_variables.index(variable)
        return indexes

    def determine_indexes_for_chose_variables_of_interest(self, session_stored_simulator):
        all_variables = session_stored_simulator.model.__class__.variables_of_interest.element_choices
        chosen_variables = session_stored_simulator.model.variables_of_interest
        indexes = self.get_variables_of_interest_indexes(all_variables, chosen_variables)
        return indexes

    def _reset_model(self, session_stored_simulator):
        session_stored_simulator.model = type(session_stored_simulator.model)()
        vi_indexes = self.determine_indexes_for_chose_variables_of_interest(session_stored_simulator)
        vi_indexes = numpy.array(list(vi_indexes.values()))
        for monitor in session_stored_simulator.monitors:
            monitor.variables_of_interest = vi_indexes

    def reset_at_connectivity_change(self, is_simulator_copy, form, session_stored_simulator):
        """
        In case the user copies a simulation and changes the Connectivity, we want to reset the Model and Noise
        parameters because they might not fit to the new Connectivity's nr of regions.
        """
        if is_simulator_copy and form.connectivity.value != session_stored_simulator.connectivity:
            self._reset_model(session_stored_simulator)
            if issubclass(type(session_stored_simulator.integrator), IntegratorStochastic):
                session_stored_simulator.integrator.noise = type(session_stored_simulator.integrator.noise)()

    def reset_at_surface_change(self, is_simulator_copy, form, session_stored_simulator):
        """
        In case the user copies a surface-simulation and changes the Surface, we want to reset the Model
        parameters because they might not fit to the new Surface's nr of vertices.
        """
        if is_simulator_copy and (session_stored_simulator.surface is None and form.surface.value
                                  or session_stored_simulator.surface and form.surface.value != session_stored_simulator.surface.surface_gid):
            self._reset_model(session_stored_simulator)

    @transactional
    def _prepare_operation(self, project_id, user_id, simulator_id, simulator_gid, algo_category, op_group, metadata,
                           ranges=None):
        operation_parameters = json.dumps({'gid': simulator_gid.hex})
        metadata, user_group = self.operation_service._prepare_metadata(metadata, algo_category, op_group, {})
        meta_str = json.dumps(metadata)

        op_group_id = None
        if op_group:
            op_group_id = op_group.id

        operation = Operation(user_id, project_id, simulator_id, operation_parameters, op_group_id=op_group_id,
                              meta=meta_str, range_values=ranges)

        self.logger.info("Saving Operation(userId=" + str(user_id) + ", projectId=" + str(project_id) + "," +
                         str(metadata) + ", algorithmId=" + str(simulator_id) + ", ops_group= " +
                         str(op_group_id) + ", params=" + str(operation_parameters) + ")")

        operation = dao.store_entity(operation)
        # TODO: prepare portlets/handle operation groups/no workflows
        return operation

    @staticmethod
    def _set_simulator_range_parameter(simulator, range_parameter_name, range_parameter_value):
        range_param_name_list = range_parameter_name.split('.')
        current_attr = simulator
        for param_name in range_param_name_list[:len(range_param_name_list) - 1]:
            current_attr = getattr(current_attr, param_name)
        setattr(current_attr, range_param_name_list[-1], range_parameter_value)

    def async_launch_and_prepare_simulation(self, burst_config, user, project, simulator_algo,
                                            session_stored_simulator):
        try:
            metadata = {}
            metadata.update({DataTypeMetaData.KEY_BURST: burst_config.id})
            simulator_id = simulator_algo.id
            algo_category = simulator_algo.algorithm_category
            operation = self._prepare_operation(project.id, user.id, simulator_id, session_stored_simulator.gid,
                                                algo_category, None, metadata)
            storage_path = self.files_helper.get_project_folder(project, str(operation.id))
            h5.store_view_model(session_stored_simulator, storage_path)
            burst_config = self.burst_service.update_simulation_fields(burst_config.id, operation.id,
                                                                       session_stored_simulator.gid)
            self.burst_service.store_burst_configuration(burst_config, storage_path)

            wf_errs = 0
            try:
                OperationService().launch_operation(operation.id, True)
                return operation
            except Exception as excep:
                self.logger.error(excep)
                wf_errs += 1
                if burst_config:
                    self.burst_service.mark_burst_finished(burst_config, error_message=str(excep))

            self.logger.debug("Finished launching workflow. The operation was launched successfully, " +
                              str(wf_errs) + " had error on pre-launch steps")

        except Exception as excep:
            self.logger.error(excep)
            if burst_config:
                self.burst_service.mark_burst_finished(burst_config, error_message=str(excep))

    def prepare_simulation_on_server(self, user_id, project, algorithm, zip_folder_path, simulator_file):
        simulator_vm = h5.load_view_model_from_file(simulator_file)
        metadata = {}
        simulator_id = algorithm.id
        algo_category = algorithm.algorithm_category
        operation = self._prepare_operation(project.id, user_id, simulator_id, simulator_vm.gid,
                                            algo_category, None, metadata)
        storage_operation_path = self.files_helper.get_project_folder(project, str(operation.id))
        self.async_launch_simulation_on_server(operation, zip_folder_path, storage_operation_path)

        return operation

    def async_launch_simulation_on_server(self, operation, zip_folder_path, storage_operation_path):
        try:
            for file in os.listdir(zip_folder_path):
                shutil.move(os.path.join(zip_folder_path, file), storage_operation_path)
            try:
                OperationService().launch_operation(operation.id, True)
                shutil.rmtree(zip_folder_path)
                return operation
            except Exception as excep:
                self.logger.error(excep)
        except Exception as excep:
            self.logger.error(excep)

    @staticmethod
    def _set_range_param_in_dict(param_value):
        if type(param_value) is numpy.ndarray:
            return param_value[0]
        elif isinstance(param_value, uuid.UUID):
            return param_value.hex
        else:
            return param_value

    def async_launch_and_prepare_pse(self, burst_config, user, project, simulator_algo, range_param1, range_param2,
                                     session_stored_simulator):
        try:
            simulator_id = simulator_algo.id
            algo_category = simulator_algo.algorithm_category
            operation_group = burst_config.operation_group
            metric_operation_group = burst_config.metric_operation_group
            operations = []
            range_param2_values = [None]
            if range_param2:
                range_param2_values = range_param2.get_range_values()
            first_simulator = None

            for param1_value in range_param1.get_range_values():
                for param2_value in range_param2_values:
                    # Copy, but generate a new GUID for every Simulator in PSE
                    simulator = copy.deepcopy(session_stored_simulator)
                    simulator.gid = uuid.uuid4()
                    self._set_simulator_range_parameter(simulator, range_param1.name, param1_value)

                    ranges = {range_param1.name: self._set_range_param_in_dict(param1_value)}

                    if param2_value is not None:
                        self._set_simulator_range_parameter(simulator, range_param2.name, param2_value)
                        ranges[range_param2.name] = self._set_range_param_in_dict(param2_value)

                    ranges = json.dumps(ranges)

                    operation = self._prepare_operation(project.id, user.id, simulator_id, simulator.gid,
                                                        algo_category, operation_group,
                                                        {DataTypeMetaData.KEY_BURST: burst_config.id}, ranges)

                    storage_path = self.files_helper.get_project_folder(project, str(operation.id))
                    h5.store_view_model(simulator, storage_path)
                    operations.append(operation)
                    if first_simulator is None:
                        first_simulator = simulator

            first_operation = operations[0]
            storage_path = self.files_helper.get_project_folder(project, str(first_operation.id))
            burst_config = self.burst_service.update_simulation_fields(burst_config.id, first_operation.id,
                                                                       first_simulator.gid)
            self.burst_service.store_burst_configuration(burst_config, storage_path)
            datatype_group = DataTypeGroup(operation_group, operation_id=first_operation.id,
                                           fk_parent_burst=burst_config.id,
                                           state=json.loads(first_operation.meta_data)[DataTypeMetaData.KEY_STATE])
            dao.store_entity(datatype_group)

            metrics_datatype_group = DataTypeGroup(metric_operation_group, fk_parent_burst=burst_config.id)
            dao.store_entity(metrics_datatype_group)

            wf_errs = 0
            for operation in operations:
                try:
                    OperationService().launch_operation(operation.id, True)
                except Exception as excep:
                    self.logger.error(excep)
                    wf_errs += 1
                    self.burst_service.mark_burst_finished(burst_config, error_message=str(excep))

            self.logger.debug("Finished launching workflows. " + str(len(operations) - wf_errs) +
                              " were launched successfully, " + str(wf_errs) + " had error on pre-launch steps")

        except Exception as excep:
            self.logger.error(excep)
            self.burst_service.mark_burst_finished(burst_config, error_message=str(excep))

    def load_from_zip(self, zip_file, project):
        import_service = ImportService()
        simulator_folder = import_service.import_simulator_configuration_zip(zip_file)

        simulator_h5_filename = DirLoader(simulator_folder, None).find_file_for_has_traits_type(SimulatorAdapterModel)
        simulator_h5_filepath = os.path.join(simulator_folder, simulator_h5_filename)
        simulator = h5.load_view_model_from_file(simulator_h5_filepath)

        burst_config = self.burst_service.load_burst_configuration_from_folder(simulator_folder, project)
        return simulator, burst_config
