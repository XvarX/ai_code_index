import gameplay

class CBox(gameplay.CHuoDong):
    def __init__(self):
        super().__init__()
        self.m_bOpenHD = False

    def NewHour(self, iHour):
        if iHour == 5:
            self.OpenHD()
        elif iHour == 10:
            self.CloseHD()

    def OpenHD(self):
        self.m_bOpenHD = True

    def CloseHD(self):
        self.m_bOpenHD = False
