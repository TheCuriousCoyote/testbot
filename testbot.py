import random
import time
import requests
import logging
import websocket
import json
import os
from solana.rpc.api import Client
from solders.transaction import Transaction, AccountMeta
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.system_program import transfer
from solana.rpc.types import TxOpts

# Configurations
SOLANA_RPC_URL = "https://api.mainnet-beta.solana.com"
PUMP_FUN_WS_URL = "wss://pumpportal.fun/api/data"
JUPITER_API_URL = "https://quote-api.jup.ag/v4/swap"
JUPITER_QUOTE_API = "https://quote-api.jup.ag/v4/quote"
DEPLOY_INTERVAL = 300  # Deploy a new token every 5 minutes
MONITOR_INTERVAL = 300  # Check token performance every 5 minutes
DUMP_THRESHOLD = 10000  # Trading volume threshold to trigger a sell order
WITHDRAWAL_ADDRESS = "BBvWTfL18ZJYAEH8SyMHMjuACd1XhmKK51hmxGxNCtGa"

# Logging setup
logging.basicConfig(filename="meme_coin_bot.log", level=logging.INFO,
                    format="%(asctime)s - %(levelname)s - %(message)s")

# Securely load private key from environment variable
PRIVATE_KEY_HEX = os.getenv("SOL_PRIVATE_KEY")
if not PRIVATE_KEY_HEX:
    logging.error("No private key found! Set SOL_PRIVATE_KEY environment variable.")
    exit(1)

creator_wallet = Keypair.from_secret_key(bytes.fromhex(PRIVATE_KEY_HEX))

# Load deployed tokens
deployed_tokens_file = "deployed_tokens.json"
if os.path.exists(deployed_tokens_file):
    with open(deployed_tokens_file, "r") as f:
        deployed_tokens = json.load(f)
else:
    deployed_tokens = []

# Function to generate random token names
def generate_token_name():
    prefixes = ["Moon", "Doge", "Pepe", "Frog", "Shiba", "Pump", "Rug", "Fomo", "Sol", "Donald", "Trump", "Musk", "Tesla", "Vance", "Inu", "Coin", "Swap", "Token", "X", "Cash", "AI", "Busty", "Asian", "Fong", "Tiffany"]
    suffixes = ["Inu", "Coin", "Swap", "Token", "X", "Cash", "AI", "Donald", "Trump", "Musk", "Tesla", "Vance", "Moon", "Doge", "Pepe", "Frog", "Shiba", "Pump", "Rug", "Fomo", "Sol", "Busty", "Asian", "Fong", "Tiffany"]
    return random.choice(prefixes) + random.choice(suffixes) + str(random.randint(100, 999))

# Retry mechanism for transactions
def send_transaction_with_retry(transaction, max_retries=5):
    for attempt in range(max_retries):
        try:
            tx_signature = solana_client.send_transaction(transaction, creator_wallet, opts=TxOpts(skip_preflight=True))
            logging.info(f"Transaction successful: {tx_signature}")
            return tx_signature
        except Exception as e:
            logging.error(f"Transaction failed (attempt {attempt+1}/{max_retries}): {str(e)}")
            time.sleep(5)
    logging.error("Max retries reached. Transaction failed.")
    return None

# Function to deploy a new meme token via Pump.fun WebSocket
def deploy_token():
    token_name = generate_token_name()
    token_supply = random.randint(1_000_000_000, 10_000_000_000)  # 1B - 10B tokens
    logging.info(f"Deploying token: {token_name} with supply {token_supply}")

    payload = {
        "action": "create_token",
        "name": token_name,
        "supply": token_supply,
        "creator_wallet": str(creator_wallet.public_key()),
        "trading_enabled": True,
        "liquidity_added": False
    }

    def on_message(ws, message):
        response = json.loads(message)
        if response.get("status") == "success":
            mint_address = response.get("mint_address")
            logging.info(f"Successfully deployed: {token_name} ({mint_address})")
            deployed_tokens.append({"name": token_name, "mint": mint_address})
            with open(deployed_tokens_file, "w") as f:
                json.dump(deployed_tokens, f)
        else:
            logging.error(f"Failed to deploy: {token_name} - {response}")

    def on_error(ws, error):
        logging.error(f"WebSocket error: {error}")
        time.sleep(5)
        deploy_token()

    while True:
        try:
            ws = websocket.WebSocketApp(PUMP_FUN_WS_URL, on_message=on_message, on_error=on_error)
            ws.run_forever()
        except Exception as e:
            logging.error(f"WebSocket disconnected, retrying: {str(e)}")
            time.sleep(10)

# Function to retrieve real-time token trading volume
def get_token_trading_volume(mint_address):
    try:
        response = requests.get(f"{JUPITER_QUOTE_API}?inputMint={mint_address}&outputMint=So11111111111111111111111111111111111111112&amount=1000000")
        response.raise_for_status()
        data = response.json()
        return data.get("outAmount", 0)
    except Exception as e:
        logging.error(f"Error retrieving volume for {mint_address}: {str(e)}")
        return 0

# Function to sell tokens using Jupiter Aggregator API
def sell_tokens(mint_address):
    logging.info(f"Selling tokens for {mint_address}")
    payload = {
        "inputMint": mint_address,
        "outputMint": "So11111111111111111111111111111111111111112",
        "amount": "1000000",
        "wallet": str(creator_wallet.public_key()),
        "slippage": 0.5
    }
    try:
        response = requests.post(JUPITER_API_URL, json=payload)
        response.raise_for_status()
        logging.info(f"Successfully sold {mint_address}")
    except Exception as e:
        logging.error(f"Failed to sell {mint_address}: {str(e)}")

# Function to withdraw profits to the specified address
def withdraw_profits():
    logging.info("Checking for available funds to withdraw.")

    try:
        balance = solana_client.get_balance(creator_wallet.public_key())["result"]["value"]
        if balance > 10000000:  # Minimum 0.01 SOL
            tx = Transaction().add(
                transfer(
                    AccountMeta(pubkey=creator_wallet.public_key(), is_signer=True, is_writable=True),
                    AccountMeta(pubkey=PublicKey(WITHDRAWAL_ADDRESS), is_signer=False, is_writable=True),
                    10000000  # Withdraw only 0.01 SOL at a time
                )
            )
            tx_signature = send_transaction_with_retry(tx)
            if tx_signature:
                logging.info(f"Profit withdrawn: 0.01 SOL to {WITHDRAWAL_ADDRESS}, Tx: {tx_signature}")
        else:
            logging.info("Not enough funds available to withdraw.")
    except Exception as e:
        logging.error(f"Failed to withdraw profits: {str(e)}")

# Function to monitor token activity and dump if it gains traction
def monitor_and_dump():
    for token in deployed_tokens:
        logging.info(f"Checking activity for {token['name']} ({token['mint']})")
        trading_volume = get_token_trading_volume(token['mint'])
        if trading_volume > DUMP_THRESHOLD:
            logging.info(f"Dumping {token['name']} ({token['mint']}): {trading_volume} SOL volume detected")
            sell_tokens(token['mint'])

# Main loop
def main():
    while True:
        deploy_token()
        time.sleep(DEPLOY_INTERVAL)
        monitor_and_dump()
        withdraw_profits()
        time.sleep(MONITOR_INTERVAL)

if __name__ == "__main__":
    main()
