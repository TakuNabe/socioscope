from socioscope_core.core.pipeline import Pipeline, Stage
from theme_growth_fertility import pipeline

PIPELINE = Pipeline(slug="growth-fertility", title="経済成長と出生率（国間・国内）")
PIPELINE.register(Stage.FETCH)(pipeline.fetch)
PIPELINE.register(Stage.STAGE)(pipeline.stage)
PIPELINE.register(Stage.MART)(pipeline.mart)
