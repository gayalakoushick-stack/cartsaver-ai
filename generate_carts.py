import json
import random
import sqlite3
import uuid
from datetime import datetime, timedelta
from faker import Faker

# Initialize Faker with Indian locale
fake = Faker('en_IN')

# Seed for reproducibility
random.seed(42)
Faker.seed(42)

DB_NAME = "cartsaver.db"
NUM_RECORDS = 300

# Constants for choices and realistic distribution weights
CUSTOMER_TYPES = ["new", "returning", "high-value"]
CUSTOMER_TYPE_WEIGHTS = [0.45, 0.40, 0.15]

PAYMENT_METHODS = ["UPI", "Card", "Netbanking", "Wallet"]
PAYMENT_METHOD_WEIGHTS = [0.55, 0.25, 0.12, 0.08]

FAILURE_REASONS = [
    "payment declined",
    "bank timeout",
    "OTP failed",
    "user exited at payment",
    "insufficient balance"
]
FAILURE_REASON_WEIGHTS = [0.20, 0.25, 0.20, 0.25, 0.10]

# Product catalog for Indian e-commerce context
PRODUCT_CATEGORIES = [
    "Wireless Noise-Canceling Earbuds",
    "Smart Fitness Watch",
    "Cotton Printed Kurta",
    "Kanjivaram Silk Saree",
    "Men's Slim Fit Denim Jeans",
    "Running Sports Shoes",
    "Stainless Steel Hot & Cold Flask 1L",
    "Non-Stick Granite Cookware Set",
    "Ergonomic Gaming Mouse",
    "Mechanical RGB Keyboard",
    "Vitamin C Face Serum 30ml",
    "Organic Green Tea 250g",
    "Handcrafted Leather Wallet",
    "Sanskrit Calligraphy Wall Frame",
    "Bluetooth Portable Speaker",
    "Laptop Backpack 30L",
    "Air Purifier with HEPA Filter",
    "Ceramic Coffee Mug Set of 4",
    "Memory Foam Pillow",
    "Electric Kettle 1.5L"
]

def generate_cart_value():
    """Generate realistic cart value between ₹100 and ₹15,000 using triangular distribution skewed to lower amounts."""
    val = random.triangular(100, 15000, 1200)
    return round(val, 2)

def generate_items():
    """Generate 1-5 product items as a list of strings."""
    num_items = random.randint(1, 5)
    selected = random.sample(PRODUCT_CATEGORIES, k=num_items)
    return selected

def create_database():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS carts (
            cart_id TEXT PRIMARY KEY,
            customer_name TEXT NOT NULL,
            customer_type TEXT NOT NULL,
            cart_value REAL NOT NULL,
            items TEXT NOT NULL,
            payment_method_attempted TEXT NOT NULL,
            failure_reason TEXT NOT NULL,
            abandoned_at TEXT NOT NULL,
            recovered INTEGER NOT NULL DEFAULT 0
        )
    """)
    conn.commit()
    return conn

def generate_data():
    now = datetime.now()
    records = []
    
    for _ in range(NUM_RECORDS):
        cart_id = str(uuid.uuid4())
        customer_name = fake.name()
        customer_type = random.choices(CUSTOMER_TYPES, weights=CUSTOMER_TYPE_WEIGHTS)[0]
        cart_value = generate_cart_value()
        items = json.dumps(generate_items(), ensure_ascii=False)
        payment_method = random.choices(PAYMENT_METHODS, weights=PAYMENT_METHOD_WEIGHTS)[0]
        failure_reason = random.choices(FAILURE_REASONS, weights=FAILURE_REASON_WEIGHTS)[0]
        
        # Random timestamp spread over the last 14 days
        random_seconds = random.randint(0, 14 * 24 * 3600)
        abandoned_at = (now - timedelta(seconds=random_seconds)).strftime("%Y-%m-%d %H:%M:%S")
        
        recovered = 0  # boolean default false
        
        records.append((
            cart_id,
            customer_name,
            customer_type,
            cart_value,
            items,
            payment_method,
            failure_reason,
            abandoned_at,
            recovered
        ))
    return records

def print_summary(conn):
    cursor = conn.cursor()
    
    print("\n" + "="*50)
    print("        SYNTHETIC ABANDONED CARTS SUMMARY        ")
    print("="*50)
    
    cursor.execute("SELECT COUNT(*) FROM carts")
    total_count = cursor.fetchone()[0]
    print(f"Total Abandoned Carts Generated: {total_count}\n")
    
    print("--- Breakdown by Failure Reason ---")
    cursor.execute("SELECT failure_reason, COUNT(*) FROM carts GROUP BY failure_reason ORDER BY COUNT(*) DESC")
    for reason, count in cursor.fetchall():
        percentage = (count / total_count) * 100
        print(f"  • {reason:<25}: {count:>3} ({percentage:5.1f}%)")
        
    print("\n--- Breakdown by Customer Type ---")
    cursor.execute("SELECT customer_type, COUNT(*) FROM carts GROUP BY customer_type ORDER BY COUNT(*) DESC")
    for cust_type, count in cursor.fetchall():
        percentage = (count / total_count) * 100
        print(f"  • {cust_type:<25}: {count:>3} ({percentage:5.1f}%)")
        
    print("="*50 + "\n")

def main():
    conn = create_database()
    cursor = conn.cursor()
    
    # Clear previous records if any to ensure clean generation of 300 records
    cursor.execute("DELETE FROM carts")
    conn.commit()
    
    records = generate_data()
    cursor.executemany("""
        INSERT INTO carts (
            cart_id, customer_name, customer_type, cart_value, items,
            payment_method_attempted, failure_reason, abandoned_at, recovered
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, records)
    conn.commit()
    
    print(f"Successfully inserted {len(records)} records into '{DB_NAME}' -> table 'carts'.")
    print_summary(conn)
    conn.close()

if __name__ == "__main__":
    main()
