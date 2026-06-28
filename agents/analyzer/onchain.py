"""onchain.py — pull raw on-chain facts about an address. No LLM, pure data."""
from web3 import Web3
from dataclasses import dataclass, asdict

# Base Sepolia public RPC (same chain TapMarket lives on).
RPC_URL = "https://sepolia.base.org"

# Minimal ERC-20 ABI for the checks we do.
ERC20_ABI = [
    {"name": "symbol", "outputs": [{"type": "string"}], "inputs": [], "stateMutability": "view", "type": "function"},
    {"name": "decimals", "outputs": [{"type": "uint8"}], "inputs": [], "stateMutability": "view", "type": "function"},
    {"name": "totalSupply", "outputs": [{"type": "uint256"}], "inputs": [], "stateMutability": "view", "type": "function"},
]


@dataclass
class AddressFacts:
    address: str
    is_contract: bool
    balance_eth: float
    nonce: int                 # tx count if EOA; ~deploys if contract
    code_size: int             # bytes of bytecode (0 = EOA)
    erc20_symbol: str | None   # populated if it looks like an ERC-20
    erc20_decimals: int | None
    erc20_total_supply: int | None


def fetch_facts(address: str, rpc_url: str = RPC_URL) -> AddressFacts:
    w3 = Web3(Web3.HTTPProvider(rpc_url))
    if not w3.is_connected():
        raise RuntimeError(f"could not connect to RPC {rpc_url}")

    addr = Web3.to_checksum_address(address)
    code = w3.eth.get_code(addr)
    code_size = len(code)
    is_contract = code_size > 0

    balance_wei = w3.eth.get_balance(addr)
    balance_eth = float(w3.from_wei(balance_wei, "ether"))
    nonce = w3.eth.get_transaction_count(addr)

    symbol = decimals = total_supply = None
    if is_contract:
        # Best-effort ERC-20 probe; ignore if it isn't one.
        try:
            token = w3.eth.contract(address=addr, abi=ERC20_ABI)
            symbol = token.functions.symbol().call()
            decimals = token.functions.decimals().call()
            total_supply = token.functions.totalSupply().call()
        except Exception:
            pass

    return AddressFacts(
        address=addr,
        is_contract=is_contract,
        balance_eth=balance_eth,
        nonce=nonce,
        code_size=code_size,
        erc20_symbol=symbol,
        erc20_decimals=decimals,
        erc20_total_supply=total_supply,
    )


if __name__ == "__main__":
    import sys, json
    target = sys.argv[1] if len(sys.argv) > 1 else "0x036CbD53842c5426634e7929541eC2318f3dCF7e"
    facts = fetch_facts(target)
    print(json.dumps(asdict(facts), indent=2))
