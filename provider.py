import os
from qgis.core import QgsProcessingProvider
from qgis.PyQt.QtGui import QIcon

from .idw_loocv_algorithm import IdwLoocvAlgorithm
from .voronoi_algorithm import VoronoiAlgorithm
from .rbf_loocv_algorithm import RbfLoocvAlgorithm
from .kriging_data_analysis import KrigingDataAnalysisAlgorithm
from .kriging_variogram import KrigingVariogramAlgorithm
from .kriging_algorithm import KrigingAlgorithm

class GeoInterpolationProvider(QgsProcessingProvider):

    def __init__(self):
        QgsProcessingProvider.__init__(self)

    def unload(self):
        pass

    def loadAlgorithms(self):
        self.addAlgorithm(IdwLoocvAlgorithm())
        self.addAlgorithm(VoronoiAlgorithm())
        self.addAlgorithm(RbfLoocvAlgorithm())
        self.addAlgorithm(KrigingDataAnalysisAlgorithm())
        self.addAlgorithm(KrigingVariogramAlgorithm())
        self.addAlgorithm(KrigingAlgorithm())

    def id(self):
        return 'geointerpolation'

    def name(self):
        return 'GeoInterpolation Analyst'

    def icon(self):
        return QIcon(os.path.join(os.path.dirname(__file__), 'icon.png'))
