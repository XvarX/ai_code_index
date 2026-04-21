import lancedb
import numpy as np

# 用临时目录测试
db = lancedb.connect("./test_lancedb")

# 插入数据
data = [
    {"id": "1", "text": "hello", "vector": [0.1] * 1024},
]
table = db.create_table("test", data)
print("count:", table.count_rows())

# 查询
results = table.search([0.1] * 1024).limit(1).to_list()
print("query:", results)
