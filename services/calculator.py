def calculate_tuition(base_price: int, discount_rate: float, years: int = 4):
    """Вычисляет стоимость за год и итог за период с учетом скидки."""
    price_per_year = base_price * (1 - discount_rate)
    total_price = price_per_year * years
    return int(price_per_year), int(total_price)