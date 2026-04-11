import gameplay
import scene

class CMonster4(gameplay.CHuoDong):
    def __init__(self):
        super().__init__()
        self.m_bOpenHD = False
        self.m_scene_id = None
        self.m_npcs = []

    def NewHour(self, iHour):
        if iHour == 14:
            self.OpenHD()
        elif iHour == 15:
            self.CloseHD()

    def OpenHD(self):
        """开启活动：创建场景并刷NPC"""
        self.m_bOpenHD = True
        print(f"[Monster4] 活动开始：{self.m_HDHame}")

        # 创建场景
        self.m_scene_id = self._create_scene()
        if self.m_scene_id:
            print(f"[Monster4] 场景创建成功：{self.m_scene_id}")

            # 刷NPC
            self._spawn_npcs()
        else:
            print("[Monster4] 场景创建失败")

    def CloseHD(self):
        """关闭活动：清理场景和NPC"""
        self.m_bOpenHD = False
        print(f"[Monster4] 活动结束：{self.m_HDHame}")

        # 清理NPC
        self._clear_npcs()

        # 清理场景
        if self.m_scene_id:
            self._destroy_scene()
            self.m_scene_id = None

    def _create_scene(self):
        """创建活动场景"""
        try:
            factory = scene.SceneFactory()
            scene_id = f"monster4_activity_{self.m_HDHame}"
            scene_obj = factory.create(scene_id)
            print(f"[Monster4] 创建场景：{scene_id}")
            return scene_id
        except Exception as e:
            print(f"[Monster4] 创建场景失败：{e}")
            return None

    def _destroy_scene(self):
        """销毁活动场景"""
        try:
            mgr = scene.SceneManager()
            print(f"[Monster4] 销毁场景：{self.m_scene_id}")
        except Exception as e:
            print(f"[Monster4] 销毁场景失败：{e}")

    def _spawn_npcs(self):
        """在场景中刷NPC"""
        npc_configs = [
            {"npc_id": 1001, "pos": (100, 200), "count": 5},
            {"npc_id": 1002, "pos": (300, 400), "count": 3},
            {"npc_id": 1003, "pos": (500, 600), "count": 2},
        ]

        for config in npc_configs:
            for _ in range(config["count"]):
                npc = self._create_npc(config["npc_id"], config["pos"])
                if npc:
                    self.m_npcs.append(npc)
                    print(f"[Monster4] 刷出NPC：{config['npc_id']} at {config['pos']}")

        print(f"[Monster4] 总共刷出 {len(self.m_npcs)} 个NPC")

    def _create_npc(self, npc_id, pos):
        """创建单个NPC"""
        npc_data = {
            "npc_id": npc_id,
            "pos": pos,
            "scene_id": self.m_scene_id,
            "status": "active"
        }
        return npc_data

    def _clear_npcs(self):
        """清理所有NPC"""
        count = len(self.m_npcs)
        self.m_npcs.clear()
        print(f"[Monster4] 清理了 {count} 个NPC")
