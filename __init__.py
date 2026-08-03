# -*- coding: utf-8 -*-
"""
This script initializes the plugin, making it known to QGIS.
"""

def classFactory(iface):
    """Load GeoInterpolation Analyst class from file GeoInterpolationAnalyst.
    
    :param iface: A QGIS interface instance.
    :type iface: QgsInterface
    """
    from .geointerpolation_analyst import GeoInterpolationAnalyst
    return GeoInterpolationAnalyst(iface)

