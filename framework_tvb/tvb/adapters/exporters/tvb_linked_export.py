# -*- coding: utf-8 -*-
#
#
# TheVirtualBrain-Framework Package. This package holds all Data Management, and
# Web-UI helpful to run brain-simulations. To use it, you also need do download
# TheVirtualBrain-Scientific Package (for simulators). See content of the
# documentation-folder for more details. See also http://www.thevirtualbrain.org
#
# (c) 2012-2022, Baycrest Centre for Geriatric Care ("Baycrest") and others
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
.. moduleauthor:: Adrian Dordea <adrian.dordea@codemart.ro>
"""

from tvb.adapters.exporters.abcexporter import ABCExporter
from tvb.core.entities import load
from tvb.core.entities.model.model_datatype import DataType
from tvb.core.neocom import h5
from tvb.core.neotraits.h5 import H5File
from tvb.storage.storage_interface import StorageInterface


class TVBLinkedExporter(ABCExporter):
    """
    """

    def __init__(self):
        self.storage_interface = StorageInterface()

    def get_supported_types(self):
        return [DataType]

    def get_label(self):
        return "TVB Format with links"

    def export(self, data, project):
        """
        Exports data type:
        1. If data is a normal data type, simply exports storage file (HDF format)
        2. If data is a DataTypeGroup creates a zip with all files for all data types
        """
        if self.is_data_a_group(data):
            download_file_name = self.get_export_file_name(data, StorageInterface.TVB_ZIP_FILE_EXTENSION)
            return self.group_export(data, project, download_file_name)
        else:
            dt_path_list = []
            self.gather_datatypes_for_copy(data, dt_path_list)

            download_file_name = self._get_export_file_name(data)
            zip_to_export = self.storage_interface.export_datatypes(dt_path_list, data, download_file_name)
            return None, zip_to_export, True

    def get_export_file_extension(self, data):
        return StorageInterface.TVB_ZIP_FILE_EXTENSION

    def skip_group_datatypes(self):
        return False
