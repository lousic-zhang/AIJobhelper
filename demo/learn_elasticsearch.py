from elasticsearch import Elasticsearch
import ssl

# ===== 方式1：忽略自签名证书验证（仅开发环境） =====
es = Elasticsearch(
    hosts=["https://localhost:9200"],
   
)

# ===== 方式2：使用自签名证书的 CA 指纹或指定证书文件 =====
# 如果知道指纹，可以这样：
# es = Elasticsearch(
#     hosts=["https://localhost:9200"],
#     basic_auth=("elastic", "your_password"),
#     ssl_assert_fingerprint="复制安装时给出的指纹（如 64e4...）"
# )
# 或者提供 CA 证书路径：
# es = Elasticsearch(
#     hosts=["https://localhost:9200"],
#     basic_auth=("elastic", "your_password"),
#     ca_certs="/path/to/http_ca.crt"
# )

# 检查连接
if es.ping():
    print("✅ ES 连接成功！")

# 索引一个文档
doc = {
    "title": "Elasticsearch 入门",
    "content": "这是一篇关于 ES 使用的文章",
    "tags": ["elasticsearch", "demo"],
    "views": 100
}

resp = es.index(index="blog", id=1, document=doc)
print(f"📄 文档已索引: {resp['_id']}")

# 获取文档
get_resp = es.get(index="blog", id=1)
print(f"📖 读取文档: {get_resp['_source']}")

# 搜索文档
search_body = {
    "query": {
        "match": {
            "content": "ES 使用"
        }
    }
}
search_resp = es.search(index="blog", body=search_body)
print(f"🔍 搜索到 {search_resp['hits']['total']['value']} 条结果")
for hit in search_resp['hits']['hits']:
    print(f"  - {hit['_source']['title']}")

# 删除文档
# es.delete(index="blog", id=1)