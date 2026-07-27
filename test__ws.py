from websocket import create_connection

print("Connecting...")

ws = create_connection("wss://stream.bybit.com/v5/public/linear")

print("Connected!")

ws.close()
