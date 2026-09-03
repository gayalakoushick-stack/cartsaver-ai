import sys
import json
import sqlite3
import random
import numpy as np
import pandas as pd

if sys.platform == "win32":
    try:
        if hasattr(sys.stdout, "reconfigure"):
            getattr(sys.stdout, "reconfigure")(encoding='utf-8')
    except Exception:
        pass

from datetime import datetime
from sklearn.model_selection import train_test_split
from sklearn.linear_model import LogisticRegression
from sklearn.tree import DecisionTreeClassifier
from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score, roc_auc_score
from sklearn.preprocessing import StandardScaler, OneHotEncoder
from sklearn.compose import ColumnTransformer
from sklearn.pipeline import Pipeline

DB_NAME = "cartsaver.db"

def load_data():
    conn = sqlite3.connect(DB_NAME)
    df = pd.read_sql_query("SELECT * FROM carts", conn)
    conn.close()
    return df

def generate_synthetic_labels(df):
    """
    Generate synthetic 'recovered' binary label using a rule-based probabilistic heuristic:
    - High cart value, high-value/returning customer, bank timeout/OTP failed -> higher recovery chance
    - Low cart value, new customer, user exited at payment -> lower recovery chance
    - Includes controlled random noise so labels are realistic and non-deterministic.
    """
    np.random.seed(42)
    random.seed(42)
    
    scores = []
    labels = []
    
    for idx, row in df.iterrows():
        # Base probability
        prob = 0.35
        
        # Cart value effect
        if row['cart_value'] > 5000:
            prob += 0.20
        elif row['cart_value'] > 2000:
            prob += 0.10
        elif row['cart_value'] < 800:
            prob -= 0.10
            
        # Customer type effect
        if row['customer_type'] == 'high-value':
            prob += 0.25
        elif row['customer_type'] == 'returning':
            prob += 0.12
        elif row['customer_type'] == 'new':
            prob -= 0.08
            
        # Failure reason effect
        if row['failure_reason'] == 'bank timeout':
            prob += 0.25
        elif row['failure_reason'] == 'OTP failed':
            prob += 0.20
        elif row['failure_reason'] == 'payment declined':
            prob += 0.05
        elif row['failure_reason'] == 'insufficient balance':
            prob -= 0.15
        elif row['failure_reason'] == 'user exited at payment':
            prob -= 0.25
            
        # Payment method effect
        if row['payment_method_attempted'] == 'UPI':
            prob += 0.05
            
        # Add random noise ~ N(0, 0.10)
        noise = np.random.normal(0, 0.10)
        final_prob = float(np.clip(prob + noise, 0.02, 0.98))
        
        # Bernoulli sample for binary recovery label
        recovered_label = 1 if np.random.rand() < final_prob else 0
        
        scores.append(final_prob)
        labels.append(recovered_label)
        
    df['recovered'] = labels
    return df

def feature_engineering(df):
    """Derive hours_since_abandonment and select features."""
    df['abandoned_at_dt'] = pd.to_datetime(df['abandoned_at'])
    ref_time = df['abandoned_at_dt'].max() + pd.Timedelta(hours=1)
    df['hours_since_abandonment'] = (ref_time - df['abandoned_at_dt']).dt.total_seconds() / 3600.0
    
    features = ['cart_value', 'customer_type', 'payment_method_attempted', 'failure_reason', 'hours_since_abandonment']
    X = df[features]
    y = df['recovered']
    return X, y, df

def train_and_evaluate_models(X, y):
    cat_cols = ['customer_type', 'payment_method_attempted', 'failure_reason']
    num_cols = ['cart_value', 'hours_since_abandonment']
    
    preprocessor = ColumnTransformer(
        transformers=[
            ('num', StandardScaler(), num_cols),
            ('cat', OneHotEncoder(sparse_output=False, handle_unknown='ignore'), cat_cols)
        ]
    )
    
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42, stratify=y)
    
    # Logistic Regression Pipeline
    lr_pipeline = Pipeline([
        ('preprocessor', preprocessor),
        ('classifier', LogisticRegression(random_state=42, max_iter=1000))
    ])
    
    # Decision Tree Pipeline
    dt_pipeline = Pipeline([
        ('preprocessor', preprocessor),
        ('classifier', DecisionTreeClassifier(random_state=42, max_depth=4))
    ])
    
    lr_pipeline.fit(X_train, y_train)
    dt_pipeline.fit(X_train, y_train)
    
    # Predictions
    y_pred_lr = lr_pipeline.predict(X_test)
    y_prob_lr = lr_pipeline.predict_proba(X_test)[:, 1]
    
    y_pred_dt = dt_pipeline.predict(X_test)
    y_prob_dt = dt_pipeline.predict_proba(X_test)[:, 1]
    
    metrics = {
        'Logistic Regression': {
            'accuracy': accuracy_score(y_test, y_pred_lr),
            'precision': precision_score(y_test, y_pred_lr, zero_division=0),
            'recall': recall_score(y_test, y_pred_lr, zero_division=0),
            'f1': f1_score(y_test, y_pred_lr, zero_division=0),
            'roc_auc': roc_auc_score(y_test, y_prob_lr)
        },
        'Decision Tree': {
            'accuracy': accuracy_score(y_test, y_pred_dt),
            'precision': precision_score(y_test, y_pred_dt, zero_division=0),
            'recall': recall_score(y_test, y_pred_dt, zero_division=0),
            'f1': f1_score(y_test, y_pred_dt, zero_division=0),
            'roc_auc': roc_auc_score(y_test, y_prob_dt)
        }
    }
    
    # Fit Logistic Regression on full dataset to calculate production recovery scores
    lr_pipeline.fit(X, y)
    all_scores = lr_pipeline.predict_proba(X)[:, 1]
    
    # Feature Importance (Logistic Regression Coefficients)
    ohe_feature_names = lr_pipeline.named_steps['preprocessor'].named_transformers_['cat'].get_feature_names_out(cat_cols)
    all_feature_names = num_cols + list(ohe_feature_names)
    coefficients = lr_pipeline.named_steps['classifier'].coef_[0]
    
    feature_importance = pd.DataFrame({
        'Feature': all_feature_names,
        'Coefficient': coefficients,
        'Abs_Coefficient': np.abs(coefficients)
    }).sort_values(by='Abs_Coefficient', ascending=False)
    
    return lr_pipeline, metrics, all_scores, feature_importance

def assign_segments(df):
    """
    Assign carts to segments based on recovery_score, cart_value, and failure_reason:
    - High-Value High-Intent: recovery_score >= 0.60 AND cart_value >= 3000
    - Payment-Failed-Technical: recovery_score >= 0.40 AND failure_reason in ('bank timeout', 'OTP failed')
    - Price-Sensitive: recovery_score < 0.40 OR cart_value < 1500
    - Low-Intent: Remaining carts (e.g. low score + user exited)
    """
    segments = []
    for _, row in df.iterrows():
        score = row['recovery_score']
        val = row['cart_value']
        reason = row['failure_reason']
        
        if score >= 0.60 and val >= 3000:
            segment = "High-Value High-Intent"
        elif score >= 0.40 and reason in ["bank timeout", "OTP failed"]:
            segment = "Payment-Failed-Technical"
        elif val < 1500 or (score < 0.40 and reason in ["user exited at payment", "insufficient balance"]):
            segment = "Price-Sensitive"
        else:
            segment = "Low-Intent"
            
        segments.append(segment)
        
    df['segment'] = segments
    return df

def compute_customer_ltv_and_priority_scores(df):
    """
    Compute customer_ltv_score (0-1) and combined priority_score (0-1):
    - customer_ltv_score based on:
        - customer_type: high-value=1.0, returning=0.6, new=0.3
        - cart_value normalized across dataset (0-1)
        - Formula: type_weight * 0.6 + norm_cart_value * 0.4
    - priority_score = recovery_score * 0.6 + customer_ltv_score * 0.4
    """
    type_map = {
        'high-value': 1.0,
        'returning': 0.6,
        'new': 0.3
    }
    type_weight = df['customer_type'].map(type_map).fillna(0.3)
    
    min_val = df['cart_value'].min()
    max_val = df['cart_value'].max()
    if max_val > min_val:
        norm_cart_val = (df['cart_value'] - min_val) / (max_val - min_val)
    else:
        norm_cart_val = pd.Series(0.5, index=df.index)
        
    ltv_score = (type_weight * 0.6 + norm_cart_val * 0.4).clip(0.0, 1.0)
    df['customer_ltv_score'] = np.round(ltv_score, 4)
    
    priority = (df['recovery_score'] * 0.6 + df['customer_ltv_score'] * 0.4).clip(0.0, 1.0)
    df['priority_score'] = np.round(priority, 4)
    
    return df

def update_database(df):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # Inspect current schema
    cursor.execute("PRAGMA table_info(carts)")
    columns = [col[1] for col in cursor.fetchall()]
    
    if "recovery_score" not in columns:
        cursor.execute("ALTER TABLE carts ADD COLUMN recovery_score REAL")
    if "segment" not in columns:
        cursor.execute("ALTER TABLE carts ADD COLUMN segment TEXT")
    if "customer_ltv_score" not in columns:
        cursor.execute("ALTER TABLE carts ADD COLUMN customer_ltv_score REAL")
    if "priority_score" not in columns:
        cursor.execute("ALTER TABLE carts ADD COLUMN priority_score REAL")
        
    conn.commit()
    
    # Update all rows
    records_to_update = [
        (
            int(row['recovered']),
            float(row['recovery_score']),
            str(row['segment']),
            float(row['customer_ltv_score']),
            float(row['priority_score']),
            str(row['cart_id'])
        )
        for _, row in df.iterrows()
    ]
    
    cursor.executemany("""
        UPDATE carts 
        SET recovered = ?, recovery_score = ?, segment = ?, customer_ltv_score = ?, priority_score = ?
        WHERE cart_id = ?
    """, records_to_update)
    
    conn.commit()
    conn.close()

def print_top_priority_carts(df):
    top10 = df.sort_values(by='priority_score', ascending=False).head(10)
    
    print("\n" + "="*95)
    print("             TOP 10 HIGHEST-PRIORITY CARTS (LTV + RECOVERY COMBINED)             ")
    print("="*95)
    print(f"{'#':<3} | {'Customer Name':<18} | {'Type':<11} | {'Value (₹)':<12} | {'Segment':<25} | {'Recov':<6} | {'LTV':<6} | {'Priority':<8}")
    print("-" * 95)
    
    for idx, (_, row) in enumerate(top10.iterrows(), 1):
        name = row['customer_name'][:18]
        cust_type = row['customer_type']
        val = f"₹{row['cart_value']:,.2f}"
        seg = row['segment'][:25]
        rec_score = f"{row['recovery_score']:.4f}"
        ltv = f"{row['customer_ltv_score']:.4f}"
        prio = f"{row['priority_score']:.4f}"
        print(f"{idx:<3} | {name:<18} | {cust_type:<11} | {val:<12} | {seg:<25} | {rec_score:<6} | {ltv:<6} | {prio:<8}")
    print("="*95 + "\n")

def main():
    print("Loading data from database...")
    df = load_data()
    
    print("Generating synthetic labels and engineering features...")
    df = generate_synthetic_labels(df)
    X, y, df = feature_engineering(df)
    
    print("Training ML models (Logistic Regression & Decision Tree)...")
    model, metrics, all_scores, feature_importance = train_and_evaluate_models(X, y)
    
    df['recovery_score'] = np.round(all_scores, 4)
    df = assign_segments(df)
    
    print("Computing customer LTV scores and combined priority scores...")
    df = compute_customer_ltv_and_priority_scores(df)
    
    print("Updating database table 'carts' with recovery scores, LTV, priority scores, and segments...")
    update_database(df)
    
    # Print Output Summaries
    print("\n" + "="*65)
    print("             ML MODEL PERFORMANCE COMPARISON             ")
    print("="*65)
    for model_name, m in metrics.items():
        print(f"\n[{model_name}]")
        print(f"  • Accuracy : {m['accuracy']*100:.2f}%")
        print(f"  • Precision: {m['precision']*100:.2f}%")
        print(f"  • Recall   : {m['recall']*100:.2f}%")
        print(f"  • F1 Score : {m['f1']*100:.2f}%")
        print(f"  • ROC-AUC  : {m['roc_auc']:.4f}")
        
    print("\n" + "="*65)
    print("       FEATURE IMPORTANCE SUMMARY (Logistic Regression)       ")
    print("="*65)
    for _, row in feature_importance.iterrows():
        direction = "Positive (+)" if row['Coefficient'] > 0 else "Negative (-)"
        print(f"  • {row['Feature']:<42}: {row['Coefficient']:+7.4f}  [{direction}]")
        
    print("\n" + "="*65)
    print("              CUSTOMER SEGMENTS BREAKDOWN              ")
    print("="*65)
    seg_summary = df.groupby('segment').agg(
        Count=('cart_id', 'count'),
        Avg_Score=('recovery_score', 'mean'),
        Avg_LTV=('customer_ltv_score', 'mean'),
        Avg_Priority=('priority_score', 'mean'),
        Avg_Value=('cart_value', 'mean')
    ).reset_index()
    
    for _, row in seg_summary.iterrows():
        print(f"  • {row['segment']:<25}: {row['Count']:>3} carts | Avg Recov: {row['Avg_Score']:.4f} | Avg Priority: {row['Avg_Priority']:.4f} | Avg Value: ₹{row['Avg_Value']:.2f}")
    print("="*65)
    
    # Print Top 10 Priority Carts
    print_top_priority_carts(df)

if __name__ == "__main__":
    main()
