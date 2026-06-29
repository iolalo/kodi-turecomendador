# Perfil personal de gustos cinematográficos — estilo MUBI
# Calibrado en base a: Train Dreams, Rental Family, Petite Maman,
# Hot Milk, A Real Pain, A Different Man, Perfect Days,
# Fallen Leaves, The Worst Person in the World

# Directores de referencia (TMDB person IDs)
# Se completan con los IDs reales de TMDB en el Paso 5
DIRECTORS = {
    "Aki Kaurismäki":     None,  # Fallen Leaves, The Match Factory Girl
    "Céline Sciamma":     None,  # Petite Maman, Portrait of a Lady on Fire
    "Kelly Reichardt":    None,  # Train Dreams, First Cow, Certain Women
    "Ryusuke Hamaguchi":  None,  # Drive My Car, Wheel of Fortune and Fantasy
    "Hong Sang-soo":      None,  # prolifico, cine minimalista coreano
    "Wim Wenders":        None,  # Perfect Days, Wings of Desire
    "Joachim Trier":      None,  # The Worst Person in the World
    "Mia Hansen-Løve":    None,  # Bergman Island, Eden
    "Hirokazu Kore-eda":  None,  # Still Walking, Shoplifters
    "Ruben Östlund":      None,  # Force Majeure, Triangle of Sadness
}

# Géneros TMDB favoritos (IDs)
GENRES = [
    18,    # Drama
    # 10749, # Romance — secundario, solo si combina con drama indie
]

# Países de producción preferidos (ISO 3166-1)
COUNTRIES = ["FI", "FR", "JP", "NO", "SE", "DK", "DE", "IT", "GB", "US"]
# US incluido pero filtrado por vote_count bajo (más indie)

# Géneros a excluir — mantienen el perfil indie/arthouse limpio
EXCLUDED_GENRES = [
    28,    # Action
    12,    # Adventure
    16,    # Animation
    878,   # Science Fiction
    27,    # Horror
    14,    # Fantasy
    10751, # Family
    10402, # Music (documentales musicales)
    10770, # TV Movie
]

# Parámetros de filtro TMDB para Discover
DISCOVER_PARAMS = {
    "sort_by": "vote_average.desc",
    "vote_count.gte": 150,   # mínimo razonable para que el rating sea confiable
    "vote_count.lte": 8000,  # excluye mainstream (Seven Samurai ~4k pasa, 12 Angry Men ~10k no)
    "vote_average.gte": 6.8,
}

# Keywords TMDB relevantes al perfil (IDs a confirmar con TMDB)
# Buscar con: https://api.themoviedb.org/3/search/keyword?query=arthouse
KEYWORDS = [
    # "arthouse", "slow cinema", "minimalism", "introspective",
    # "coming of age", "slice of life", "melancholy"
    # Se completan con IDs reales en el Paso 4
]
