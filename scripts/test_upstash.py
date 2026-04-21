import os
from upstash_redis import Redis

r = Redis(os.environ["UPSTASH_REDIS_URL"], os.environ["UPSTASH_REDIS_TOKEN"])

# Test basic insert
r.set("test_key", "value", ex=60, nx=True)
print("Exists:", r.exists("test_key"))

# Test pipeline
pipe = r.pipeline()
pipe.set("test_pipe_1", "1", ex=60)
pipe.set("test_pipe_2", "2", ex=60)
results = pipe.exec()
print("Pipeline results:", results)

# Test scan
cursor, keys = r.scan(0, match="*", count=10)
print("Keys:", keys)
