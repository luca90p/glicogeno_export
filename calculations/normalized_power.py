
def calculate_normalized_power(df):
    if 'power' not in df.columns:
        return 0
    rolling_pwr = df['power'].rolling(window=30, min_periods=1).mean()
    return (rolling_pwr ** 4).mean() ** 0.25
