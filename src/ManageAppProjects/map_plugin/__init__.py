# coding: utf-8
""" Модуль загрузки плагина. """
from py_common.plugins import PluginMetadata, import_package_modules


def plugin_metadata() -> PluginMetadata:
    """ Метаданные плагина """

    return PluginMetadata(is_root=True)


import_package_modules(__file__, __package__)
