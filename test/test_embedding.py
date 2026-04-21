"""
test_embedding.py - 测试 Embedding API + ChromaDB
验证向量化入库和查询的完整流程
"""

from openai import OpenAI
import chromadb
import os

# 配置
BASE_URL = "https://open.bigmodel.cn/api/paas/v4"
API_KEY = "fc39a6e1d4dc485e9ac875eb677419b3.xWoPVB7G5KFw5mIp"
MODEL = "embedding-3"

client = OpenAI(api_key=API_KEY, base_url=BASE_URL)

# 测试数据：模拟几个游戏服务器代码块
test_chunks = [
    {
        "id": "scene/create_scene",
        "text": "创建游戏场景。根据地图ID创建场景实例，加载NPC和怪物配置，初始化场景定时器。",
        "code": "def create_scene(map_id: int) -> Scene:\n    config = load_map_config(map_id)\n    scene = Scene(map_id, config)\n    spawn_npcs(scene, config.npc_list)\n    return scene",
        "meta": {"module": "scene", "action": "create", "target": "scene"},
    },
    {
        "id": "reward/give_reward",
        "text": "发放奖励给玩家。检查背包空间，创建奖励邮件，添加道具到玩家背包。",
        "code": "def give_reward(player_id: int, reward_list: list) -> bool:\n    player = get_player(player_id)\n    for item in reward_list:\n        player.add_item(item)\n    return True",
        "meta": {"module": "reward", "action": "give", "target": "reward"},
    },
    {
        "id": "npc/spawn_npc",
        "text": "在场景中生成NPC。根据配置ID生成NPC实例，设置位置和AI行为树。",
        "code": "def spawn_npc(scene: Scene, npc_id: int, pos: Position) -> NPC:\n    config = load_npc_config(npc_id)\n    npc = NPC(npc_id, config)\n    npc.set_position(pos)\n    scene.add_entity(npc)\n    return npc",
        "meta": {"module": "scene", "action": "create", "target": "npc"},
    },
    {
        "id": "activity/daily_sign",
        "text": "每日签到活动。玩家每天登录签到领奖，连续7天有额外奖励，每月重置。",
        "code": "class DailySignActivity:\n    def on_sign(self, player_id: int) -> Reward:\n        self.check_reset()\n        day = self.get_continuous_days(player_id)\n        reward = self.calc_reward(day)\n        give_reward(player_id, reward)\n        return reward",
        "meta": {"module": "activity", "action": "handle", "target": "dailysign"},
    },
    {
        "id": "battle/start",
        "text": "开始战斗。初始化战斗回合，设置双方阵容，启动战斗引擎。",
        "code": "def start_battle(attacker: Player, defender: Player) -> Battle:\n    battle = Battle(attacker, defender)\n    battle.init_round()\n    battle.start_engine()\n    return battle",
        "meta": {"module": "battle", "action": "start", "target": "battle"},
    },
]


def embed_texts(texts):
    """调用 Embedding API"""
    print(f"  调用 Embedding API，{len(texts)} 条文本...")
    resp = client.embeddings.create(model=MODEL, input=texts)
    sorted_data = sorted(resp.data, key=lambda x: x.index)
    return [item.embedding for item in sorted_data]


def main():
    # 1. 测试 Embedding API
    print("=" * 50)
    print("Step 1: 测试 Embedding API")
    texts = [f"{c['text']}\n{c['code']}" for c in test_chunks]
    embeddings = embed_texts(texts)
    print(f"  向量维度: {len(embeddings[0])}")
    print(f"  向量前5位: {embeddings[0][:5]}")
    print(f"  OK\n")

    # 2. 存入 ChromaDB
    print("Step 2: 存入 ChromaDB")
    db_path = os.path.join(os.path.dirname(__file__), "data", "test_chroma")
    db_client = chromadb.PersistentClient(path=db_path)
    # 清除旧测试数据
    try:
        db_client.delete_collection("test_code")
    except Exception:
        pass

    collection = db_client.get_or_create_collection(
        name="test_code",
        metadata={"hnsw:space": "cosine"},
    )

    collection.add(
        ids=[c["id"] for c in test_chunks],
        documents=texts,
        embeddings=embeddings,
        metadatas=[c["meta"] for c in test_chunks],
    )
    print(f"  存入 {len(test_chunks)} 条数据")
    print(f"  OK\n")

    # 3. 测试查询
    print("Step 3: 测试查询")
    queries = [
        ("怎么创建场景", None),
        ("给玩家发奖", {"module": "reward"}),
        ("生成NPC", {"module": "scene"}),
        ("怎么打战斗", None),
    ]

    for query_text, where_filter in queries:
        query_emb = embed_texts([query_text])
        kwargs = {
            "query_embeddings": query_emb,
            "n_results": 2,
        }
        if where_filter:
            kwargs["where"] = where_filter

        results = collection.query(**kwargs)

        print(f"\n  查询: \"{query_text}\"" + (f" (过滤: {where_filter})" if where_filter else ""))
        for i, doc_id in enumerate(results["ids"][0]):
            meta = results["metadatas"][0][i]
            dist = results["distances"][0][i]
            print(f"    -> {doc_id} | 模块:{meta['module']} 动作:{meta['action']} 距离:{dist:.4f}")

    # 4. 清理测试数据
    print("\n" + "=" * 50)
    print("测试完成！清理测试数据库...")
    db_client.delete_collection("test_code")
    import shutil
    shutil.rmtree(db_path, ignore_errors=True)
    print("已清理。")


if __name__ == "__main__":
    main()
