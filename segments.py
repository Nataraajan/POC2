"""Illustrative POC segments, NOT the brands' actual product catalogue or credit assumptions."""

LOAN_TERMS = {"Line of Credit": 12, "Installment": 24}
BRANDS = ("CreditFresh", "MoneyKey")


def segment_key(brand, loan_type):
    return f"{brand} {loan_type}"


# Synthetic history retains the old 58/42 brand mix; each brand is split 40/60
# by loan type. These sampling shares do not set forecast application volumes.
SEGMENTS = {
    "CreditFresh Line of Credit": dict(brand="CreditFresh", loan_type="Line of Credit", share=.232, ticket=1800., term_months=12, lifetime_default=.20, default_k=2.2, payoff_k=2.5),
    "CreditFresh Installment": dict(brand="CreditFresh", loan_type="Installment", share=.348, ticket=1800., term_months=24, lifetime_default=.16, default_k=1.6, payoff_k=1.8),
    "MoneyKey Line of Credit": dict(brand="MoneyKey", loan_type="Line of Credit", share=.168, ticket=700., term_months=12, lifetime_default=.36, default_k=2.8, payoff_k=3.0),
    "MoneyKey Installment": dict(brand="MoneyKey", loan_type="Installment", share=.252, ticket=700., term_months=24, lifetime_default=.28, default_k=2.0, payoff_k=2.1),
}
