import os
import sys
import time
import grpc
import base58
import threading

import generated.geyser_pb2 as pb_pb2
import generated.geyser_pb2_grpc as pb_pb2_grpc

results = {}     
delay_sums = {}     
detections = {}
ranking = []
totalDetections = 0

grpcs = {
    "node 1": {
        "url": "",
        "grpcToken": ""
    },
    "node 2": {
        "url": "",
        "grpcToken": "" 
    }
}

benchmarkDuration = 5
testAddress = ""

grpcCount = len(grpcs)
lock = threading.Lock()

if grpcCount < 2:
    print("You must use a minimum of 2 gRPCs.")
    sys.exit(0)

def subscribe(nodeName: str, nodeData: dict, subscription, nodeCount: int):
    global totalDetections
    nodeUrl = nodeData["url"]
    token = nodeData.get("grpcToken", "")

    try:
        if nodeUrl.startswith("https://"):
            host = nodeUrl[len("https://"):]
            credentials = grpc.ssl_channel_credentials()
            channel = grpc.secure_channel(host, credentials)
        else:
            host = nodeUrl[len("http://"):]
            channel = grpc.insecure_channel(host)
        client = pb_pb2_grpc.GeyserStub(channel)
    except Exception as e:
        print(f"Failed to create gRPC client on {nodeName} ({nodeUrl}) - {e}")
        return

    try:
        if token:
            stream = client.Subscribe(iter([subscription]), metadata=(("x-token", token)))
        else:
            stream = client.Subscribe(iter([subscription]))
    except Exception as e:
        print(f"Failed to stream on {nodeName} ({nodeUrl}) - {e}")
        return

    try:
        for msg in stream:
            if msg.HasField("transaction"):
                tx = msg.transaction
                signature = base58.b58encode(bytes(tx.transaction.signature)).decode()
                detection = {
                    "grpc": nodeName,
                    "timestamp": time.time_ns()
                }
                with lock:
                    if signature not in detections:
                        detections[signature] = [detection]
                    else:
                        detections[signature].append(detection)
                    if len(detections[signature]) == nodeCount:
                        totalDetections += 1
                        sorted_detections = sorted(detections[signature], key=lambda d: d["timestamp"])
                        winner = sorted_detections[0]["grpc"]
                        results[winner] += 1
                        delays = [det["timestamp"] - sorted_detections[0]["timestamp"] for det in sorted_detections[1:]]
                        delay = sum(delays) / len(delays) if delays else 0
                        delay_sums[winner] += delay
                        del detections[signature]

    except grpc.RpcError as e:
        print(f"Failed, RPC error on {nodeName} ({nodeUrl}) - {e}")
    except Exception as e:
        print(f"Failed - {nodeName} ({nodeUrl}) - {e}")


def main():
    global totalDetections

    grpcFilter = {
        "filter": pb_pb2.SubscribeRequestFilterTransactions(
            account_include=[testAddress], 
            failed=False
        )
    }
    
    subscription = pb_pb2.SubscribeRequest(
        transactions=grpcFilter, 
        commitment=pb_pb2.CommitmentLevel.CONFIRMED
    )

    for nodeName in grpcs.keys():
        results[nodeName] = 0
        delay_sums[nodeName] = 0

    print("[+] Testing...")

    threads = []
    for nodeName, nodeData in grpcs.items():
        t = threading.Thread(
            target=subscribe,
            args=(nodeName, nodeData, subscription, grpcCount),
            daemon=True
        )
        t.start()
        threads.append(t)

    for remaining in range(benchmarkDuration, 0, -1):
        print(f"\r[+] Time Left: {remaining:2d}s", end="")
        time.sleep(1)

    if totalDetections == 0:
        print("\n[-] No transactions detected.")
        return

    for nodeName, wins in results.items():
        winrate = (wins / totalDetections) * 100
        avgDelay = (delay_sums[nodeName] / wins) / 1e6 if wins > 0 else 0

        ranking.append({
            "node": nodeName,
            "wins": wins,
            "winrate": winrate,
            "delay": avgDelay
        })
    ranking.sort(key=lambda r: r["wins"], reverse=True)

    os.system("clear||cls")

    print(f"Total Transactions: {totalDetections:,}")
    for i, res in enumerate(ranking, start=1):
        print(f"[{i}] Name: {res['node']} | Came First: {res['wins']} times | Winrate: {res['winrate']:.2f}% | Average Delay: {res['delay']:.2f} ms")


if __name__ == "__main__":
    main()
