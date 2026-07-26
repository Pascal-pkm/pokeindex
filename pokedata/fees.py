# -*- coding: utf-8 -*-
"""Transaktionskostenmodell.

Warum das gebraucht wird: Ein Screening, das Brutto-Marktpreise vergleicht,
überschätzt jede Kaufgelegenheit systematisch. Realisierbar ist nur
    Verkaufspreis - Verkaufsprovision - Zahlungsgebühr - Versand
und beim Kauf kommt der Spread zwischen Angebots- und Verkaufspreis hinzu.
Bei Sealed-Produkten mit 5-15 % Gebührenlast entscheidet das darüber, ob ein
Signal überhaupt eine Nettorendite trägt.

Die Sätze sind Stand Juli 2026 recherchiert, ausdrücklich als Parameter
gehalten und im Report mitgeführt (`as_dict`), damit jede Auswertung ihre
Kostenannahme dokumentiert. Quellen siehe README (Abschnitt Kostenmodell).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class FeeModel:
    """Kosten einer Verkaufstransaktion an einem Handelsplatz."""
    name: str
    commission_pct: float          # Verkaufsprovision auf den Bruttopreis
    fixed_fee: float = 0.0         # Festgebühr je Bestellung
    payment_pct: float = 0.0       # Zahlungsabwicklung (falls separat)
    shipping_cost: float = 0.0     # typische Versandkosten des Verkäufers
    shipping_borne_by_buyer: bool = True
    note: str = ""

    def net_proceeds(self, gross_price: float, quantity: int = 1) -> float:
        """Netto-Erlös eines Verkaufs (EUR) bei gegebenem Bruttopreis je Stück."""
        gross = gross_price * quantity
        fees = gross * (self.commission_pct + self.payment_pct) + self.fixed_fee
        if not self.shipping_borne_by_buyer:
            fees += self.shipping_cost
        return gross - fees

    def total_fee_pct(self, gross_price: float, quantity: int = 1) -> float:
        gross = gross_price * quantity
        if gross <= 0:
            return 0.0
        return 1 - self.net_proceeds(gross_price, quantity) / gross

    def as_dict(self) -> dict:
        return asdict(self)


# Recherchierte Standardmodelle (Juli 2026).
#   Cardmarket: ~5 % Verkäuferprovision, all-in je nach Zahlungsart 6-8 %.
#   eBay.de (privat): 11 % variable Provision bis 1.990 EUR + 0,35 EUR Fixgebühr.
#   Privatverkauf/lokal: keine Plattformgebühr, dafür Versand/Aufwand.
FEE_MODELS = {
    "cardmarket.com": FeeModel("Cardmarket", 0.05, 0.0, 0.01, 4.99, True,
                               "5 % Provision, Zahlungsabwicklung ~1 %"),
    "ebay.de": FeeModel("eBay.de (privat)", 0.11, 0.35, 0.0, 5.49, True,
                        "11 % bis 1.990 EUR, 0,35 EUR Fixgebühr"),
    "amazon.de": FeeModel("Amazon.de", 0.15, 0.0, 0.0, 4.99, True,
                          "15 % Kategorieprovision (Spielwaren)"),
    "pokemoncenter.de": FeeModel("Pokémon Center (nur Kauf)", 0.0, 0.0, 0.0, 0.0,
                                 True, "Retail, kein Verkaufskanal"),
    "privat": FeeModel("Privatverkauf", 0.0, 0.0, 0.0, 0.0, True,
                       "keine Plattformgebühr"),
}

DEFAULT_MODEL = FEE_MODELS["cardmarket.com"]

# Aufschlag zwischen Angebotspreis (Ask, z. B. Cardmarket-Trend/Skinport-Listing)
# und tatsächlich erzielbarem Verkaufspreis. Wird auf Bewertungen angewandt,
# wenn die Preisquelle angebotsbasiert ist.
ASK_TO_SALE_HAIRCUT = 0.05


def model_for(platform: str | None) -> FeeModel:
    if not platform:
        return DEFAULT_MODEL
    return FEE_MODELS.get(platform.strip().lower(), DEFAULT_MODEL)


def net_of_fees(gross_price: float, platform: str | None = None,
                quantity: int = 1) -> float:
    return model_for(platform).net_proceeds(gross_price, quantity)


def breakeven_price(cost_basis: float, platform: str | None = None) -> float:
    """Bruttopreis, ab dem ein Verkauf die Anschaffungskosten deckt."""
    m = model_for(platform)
    denom = 1 - (m.commission_pct + m.payment_pct)
    if denom <= 0:
        return float("inf")
    extra = m.fixed_fee + (0.0 if m.shipping_borne_by_buyer else m.shipping_cost)
    return (cost_basis + extra) / denom
