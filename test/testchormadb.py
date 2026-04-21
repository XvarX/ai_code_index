import chromadb
# 用内存模式测试，排除数据库文件问题
client = chromadb.EphemeralClient()
col = client.create_collection("test")
col.add(ids=["1"], documents=["hello"], embeddings=[[0.1]*1024])
print("count:", col.count())
print("query:", col.query(query_embeddings=[[0.1]*1024], n_results=1))
