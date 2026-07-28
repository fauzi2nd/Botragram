class SignalManager:

    def __init__(self):
        self.last_signal = None

    def update(self, signal):

        if signal == self.last_signal:
            return None

        self.last_signal = signal
        return signal

    def reset(self):
        self.last_signal = None
