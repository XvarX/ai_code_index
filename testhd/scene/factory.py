from .manager import SceneManager

"""场景工厂"""
class SceneFactory:
    def create(self, scene_type):
        """创建场景"""
        mgr = SceneManager()
        return mgr.create_scene(scene_type)
