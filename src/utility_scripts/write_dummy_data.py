import asyncio
import requests
import json
import datetime
import random

url = 'http://10.192.0.2:30260/api/metrics/'

for i in range(25000):
    data = {
        "run_id": 1,
        "name": 'test_metric @ {}'.format(0),#random.randint(0, 7)),
        "cumulative": False,
        "date": str(datetime.datetime.now()),
        "value": str(random.random() * 100),
        "metadata": {'epoch': i, 'rank': 0}
        }

    requests.post(url, data=data)

    if i % 1000 == 0:
        print(i)


# async def main():
#     loop = asyncio.get_event_loop()
#     futures = [
#         loop.run_in_executor(
#             None,
#             requests.post,
#             url,
#             {
#                 "run_id": 3,
#                 "name": 'test_metric @ 0',
#                 "cumulative": False,
#                 "date": str(datetime.datetime.now()),
#                 "value": str(random.random() * 100),
#                 "metadata": {'epoch': i, 'rank': 0}
#                 }
#         )
#         for i in range(100000)
#     ]
#     for response in await asyncio.gather(*futures):
#         pass

# loop = asyncio.get_event_loop()
# loop.run_until_complete(main())

# async def main():
#     loop = asyncio.get_event_loop()
#     futures = [
#         loop.run_in_executor(
#             None,
#             requests.get,
#             "http://10.192.0.2:31635/api/metrics/3/?since=1970-01-01T00%3A00%3A00.000Z&metric_type=run&summarize=1000"
#         )
#         for i in range(100)
#     ]
#     for response in await asyncio.gather(*futures):
#         pass

# loop = asyncio.get_event_loop()
# loop.run_until_complete(main())