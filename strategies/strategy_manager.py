class StrategyManager:

    def __init__(self, strategy):
        self.strategy = strategy

    def analyze(self, market):
        return self.strategy.analyze(market)
