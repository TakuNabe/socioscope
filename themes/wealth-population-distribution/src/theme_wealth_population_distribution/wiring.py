from socioscope_core.core.pipeline import Pipeline, Stage
from theme_wealth_population_distribution import pipeline

PIPELINE = Pipeline(slug="wealth-population-distribution", title="人口分布と資産分布の変遷")
PIPELINE.register(Stage.FETCH)(pipeline.fetch)
PIPELINE.register(Stage.STAGE)(pipeline.stage)
PIPELINE.register(Stage.MART)(pipeline.mart)
