# -*- coding: utf-8 -*-
"""
Merger3.0 - laczenie baz AA (Enova) i Strato z algorytmem "Missing Connection".

WEJSCIE : dwa pliki CSV (baza AA / Enova oraz baza Strato / Auditdata), separator ';'.
WYJSCIE : folder z 6 plikami wynikowymi (4T/AUD) + TRASH + Podsumowanie.

RDZEN DOPASOWANIA:
    Para AA<->Strato pasuje, gdy zgadza sie NAZWA (imie + nazwisko)
    ORAZ co najmniej jeden identyfikator: PESEL / Tel. kom. / Email / Tel. dom.
    Prog nazwy zalezy od pliku:
        - Pliki 1, 2, 3 : NAZWA = 100% (dokladnie takie samo imie i nazwisko)
        - Pliki 5, 6    : NAZWA fuzzy 90-99% (literowki / drobne roznice)

UWAGA: pliki sa NIEZALEZNYMI filtrami (kopiami wybranych rekordow). Nic nie jest usuwane
z danych zrodlowych, a ten sam rekord moze trafic do kilku plikow naraz (np. Plik 2, 3 i 6).

PLIKI WYNIKOWE:
    Pliki 1/2/3 maja dwie pierwsze kolumny: Kod AA i Nr Strato, a dalej wszystkie pozostale dane
    pacjenta AA oraz (jesli istnieje) powiazanego pacjenta Strato.

    Plik 1 [4T]  : pacjent AA BEZ Nr Strato, znaleziono pewne dopasowanie 1:1 -> dodac Nr Strato
    Plik 2 [4T]  : pacjent AA polaczony BLEDNIE (nazwa nie 100% lub numeru brak w Strato) -> usunac Nr Strato
                   (WSZYSTKIE bledne polaczenia; Nr Strato = stary)
    Plik 3 [4T]  : pacjent AA polaczony BLEDNIE, znaleziono wlasciwy zamiennik 100% -> dodac nowy
                   (podzbior Pliku 2; Nr Strato = nowy)
    Plik 4 [AUD] : wszystkie rekordy AA bedace dzialalnosciami gospodarczymi (pelne kolumny AA);
                   rekordy z Pliku 4 sa wylaczone z Plikow 1, 2, 3, 5, 6
    Plik 5 [AUD] : kandydaci niepewni - AA bez Nr Strato pasujacy po kryteriach, ale niepewnie
                   (jeden wiersz = dane AA + dane Strato)
    Plik 6 [AUD] : nazwy do sprawdzenia - istniejace polaczenia z fuzzy nazwa 90-99%
                   (jeden wiersz = dane AA + dane Strato)
"""

import os
import sys
import pandas as pd
from rapidfuzz import fuzz

def log(msg):
    """Wypisuje komunikat z flush=True, by pojawial sie natychmiast (a nie po zakonczeniu)."""
    print(msg, flush=True)

# ==========================================
# KONFIGURACJA
# ==========================================
# --- PRZELACZNIKI GLOWNE ---
# 1 = odfiltruj rekordy-smieci (0000 / test / puste nazwy i kontakty) do pliku TRASH przed dopasowaniem
# 0 = smieci biora udzial w dopasowaniu jak reszta (plik TRASH bedzie pusty)
FILTER_TRASH = 1

# 1 = odfiltruj pacjentow nieaktywnych do pliku "Nieaktywni" przed dopasowaniem
# 0 = nieaktywni biora udzial w dopasowaniu jak reszta
FILTER_INACTIVE = 1

# Wartosci kolumny statusu oznaczajace pacjenta AKTYWNEGO (osobno dla kazdej bazy).
# Kazda inna wartosc (w tym pusta) jest traktowana jako NIEAKTYWNY. Porownanie ignoruje wielkosc liter.
AA_ACTIVE_STATUS_VALUES = ['Aktywny']    # AA (Enova): aktywny = "Aktywny"
ST_ACTIVE_STATUS_VALUES = ['1']          # Strato: aktywny = "1"

# Progi dopasowania nazwy
NAME_EXACT = 100        # dokladne dopasowanie imienia i nazwiska (Pliki 1, 2, 3)
NAME_FUZZY_MIN = 90     # dolna granica fuzzy (Pliki 5, 6): 90 <= score < 100

# Ochrona przed "wybuchem" par. Jesli ta sama wartosc identyfikatora (PESEL / telefon / email)
# powtarza sie czesciej niz ponizej po ktorejkolwiek stronie, jest traktowana jako placeholder
# (np. wspolny numer rejestracji) i pomijana w dopasowaniu. Ustaw 0, aby wylaczyc ochrone.
MAX_KEY_OCCURRENCES = 100

# Slowa-klucze oznaczajace smieci (TRASH)
GARBAGE_KEYWORDS = ['test', 'brak', 'nieznany', 'n/a', 'brak danych', 'puste']

# Wartosc kolumny Grupa oznaczajaca pacjenta (reszta = biznes)
GRUPA_PATIENT = '\\PACJENCI\\'

# Slowa-klucze wskazujace jednoznacznie na dzialalnosc gospodarcza (heurystyka pomocnicza do Pliku 4)
BUSINESS_KEYWORDS = ['sp. z o.o', 'sp.z o.o', 'z o.o', 's.a', 'spolka', 'spółka',
                     'sp. j', 'sp.j', 'sp. k', 'sp.k', 'fundacja', 'stowarzyszenie',
                     'p.p.h', 'przedsiebiorstwo', 'gabinet', 'firma', 'zaklad']

# ------------------------------------------
# NAZWY KOLUMN - baza AA (Enova)
# UWAGA: dopasuj do rzeczywistych naglowkow w pliku CSV z AA.
# ------------------------------------------
AA_KOD       = 'Numer pacjenta w Enovie (Kod)'  # identyfikator pacjenta AA -> kolumna wynikowa "Kod AA"
AA_STRATO    = 'Numer Strato'                   # przypisany Nr Strato (moze byc pusty)
AA_PESEL     = 'PESEL'
AA_DATA_UR   = 'Data urodzenia'
AA_IMIE      = 'Imie'                           # UWAGA: w eksporcie AA bez ogonka (Imie, nie Imię)
AA_NAZWISKO  = 'Nazwisko'
AA_NAZWA     = 'Kontrahenci.Nazwa'              # rezerwowo: gdy brak osobnych kolumn Imie/Nazwisko (w tym eksporcie nieobecna)
AA_KOD_POCZT = 'Kod pocztowy'
AA_MIEJSC    = 'Miejscowość'
AA_ULICA     = 'Ulica'
AA_NR_DOMU   = 'NrDomu'
AA_NR_LOKALU = 'NrLokalu'
AA_EMAIL     = 'Email'
AA_TEL_STAC  = 'Telefon stacjonarny'            # traktowany jako "telefon domowy" w dopasowaniu
AA_TEL_KOM   = 'Telefon komórkowy'
AA_NIP       = 'NIP'
AA_FORMA     = 'Forma prawna'
AA_VAT       = 'Podatnik VAT'
AA_GRUPA     = 'Grupa'
AA_STATUS    = 'Status Pacjenta'

# ------------------------------------------
# NAZWY KOLUMN - baza Strato (Auditdata)
# ------------------------------------------
ST_NR        = 'Nr Pacjenta'                    # numer pacjenta w Strato -> kolumna wynikowa "Nr Strato"
ST_PESEL     = 'PESEL'
ST_IMIE      = 'Imię'
ST_NAZWISKO  = 'Nazwisko'
ST_DATA      = 'Data utworzenia'
ST_KOD_POCZT = 'Kod pocztowy'
ST_MIASTO    = 'Miasto'
ST_ADRES1    = 'Adres 1'
ST_ADRES2    = 'Adres 2'
ST_ADRES3    = 'Adres 3'
ST_EMAIL     = 'Email'
ST_TEL_DOM   = 'Telefon domowy'
ST_TEL_KOM   = 'Telefon komórkowy'
ST_TEL_PRACA = 'Telefon do pracy'
ST_STATUS    = 'Status pacjenta'                # UWAGA: w Strato z malej litery (inaczej niz w AA)

# Listy oczekiwanych kolumn (do dopasowania naglowkow niezaleznie od wielkosci liter/spacji)
AA_ALL_COLS = [AA_KOD, AA_STRATO, AA_PESEL, AA_DATA_UR, AA_IMIE, AA_NAZWISKO, AA_KOD_POCZT,
               AA_MIEJSC, AA_ULICA, AA_NR_DOMU, AA_NR_LOKALU, AA_EMAIL, AA_TEL_STAC, AA_TEL_KOM,
               AA_NIP, AA_FORMA, AA_VAT, AA_GRUPA, AA_STATUS]
ST_ALL_COLS = [ST_NR, ST_PESEL, ST_IMIE, ST_NAZWISKO, ST_DATA, ST_KOD_POCZT, ST_MIASTO,
               ST_ADRES1, ST_ADRES2, ST_ADRES3, ST_EMAIL, ST_TEL_DOM, ST_TEL_KOM, ST_TEL_PRACA, ST_STATUS]


# ==========================================
# FUNKCJE POMOCNICZE - normalizacja
# ==========================================
def _empty_series(n):
    return pd.Series([None] * n)

def norm_id(series):
    """Normalizuje identyfikator Strato do porownania: usuwa .0, spacje, WIELKIE litery,
    oraz WIODACE ZERA (Strato zapisuje np. '0175218', a AA '175218' - to ten sam numer)."""
    # UWAGA: pandas 3.0 nie zamienia juz NaN na 'nan' w astype(str) - stad fillna('') na wejsciu
    s = series.fillna('').astype(str).str.replace(r'\.0$', '', regex=True).str.strip().str.upper()
    s = s.replace({'NAN': '', 'NONE': '', 'NAT': ''})
    return s.str.lstrip('0')  # 0175218 -> 175218 (rownowazne numery)

def norm_phone(series):
    """Zostawia tylko cyfry i bierze ostatnie 9 (numer krajowy)."""
    s = series.fillna('').astype(str).str.replace(r'\.0$', '', regex=True).str.replace(r'\D', '', regex=True)
    s = s.apply(lambda x: str(x)[-9:] if len(str(x)) >= 9 else str(x))
    return s.replace({'': None, 'nan': None, 'none': None})

# Wagi cyfry kontrolnej PESEL (standard GUS)
_PESEL_WEIGHTS = [1, 3, 7, 9, 1, 3, 7, 9, 1, 3]

def is_valid_pesel(pesel):
    """Sprawdza poprawnosc numeru PESEL: 11 cyfr + zgodna cyfra kontrolna.
    Cyfra kontrolna = (10 - (suma(cyfra_i * waga_i) mod 10)) mod 10 dla pierwszych 10 cyfr."""
    if pesel is None:
        return False
    p = ''.join(ch for ch in str(pesel) if ch.isdigit())
    if len(p) != 11:
        return False
    total = sum(int(p[i]) * _PESEL_WEIGHTS[i] for i in range(10))
    control = (10 - (total % 10)) % 10
    return control == int(p[10])

def norm_pesel(series):
    """Czysci PESEL do samych cyfr i zostawia TYLKO poprawne (11 cyfr + suma kontrolna).
    Niepoprawne / niepelne numery -> None (nie biora udzialu w dopasowaniu)."""
    s = series.fillna('').astype(str).str.replace(r'\D', '', regex=True)
    return s.apply(lambda x: x if is_valid_pesel(x) else None)

# Wagi cyfry kontrolnej NIP
_NIP_WEIGHTS = [6, 5, 7, 2, 3, 4, 5, 6, 7]

def is_valid_nip(nip):
    """Sprawdza poprawnosc numeru NIP: 10 cyfr + zgodna cyfra kontrolna.
    Cyfra kontrolna = suma(cyfra_i * waga_i) mod 11 dla pierwszych 9 cyfr.
    Wynik 10 oznacza numer niepoprawny (cyfra kontrolna nie moze byc 10)."""
    if nip is None:
        return False
    d = ''.join(ch for ch in str(nip) if ch.isdigit())
    if len(d) != 10:
        return False
    total = sum(int(d[i]) * _NIP_WEIGHTS[i] for i in range(9))
    control = total % 11
    if control == 10:
        return False
    return control == int(d[9])

def norm_nip(series):
    """Czysci NIP do samych cyfr i zostawia TYLKO poprawne (10 cyfr + suma kontrolna); reszta -> None."""
    s = series.fillna('').astype(str).str.replace(r'\D', '', regex=True)
    return s.apply(lambda x: x if is_valid_nip(x) else None)

def norm_email(series):
    s = series.fillna('').astype(str).str.strip().str.lower()
    return s.replace({'nan': '', 'none': ''})

def norm_name(series):
    s = series.fillna('').astype(str).str.strip().str.lower()
    return s.replace({'nan': '', 'none': ''})

def fuzzy_score(name1, name2):
    """Podobienstwo nazw 0-100 (token_sort_ratio - ignoruje kolejnosc slow)."""
    if pd.isna(name1) or pd.isna(name2):
        return 0
    a, b = str(name1).strip(), str(name2).strip()
    if a == '' or b == '':
        return 0
    return fuzz.token_sort_ratio(a.lower(), b.lower())

def drop_internal(df):
    """Usuwa kolumny pomocnicze (zaczynajace sie od '_')."""
    return df[[c for c in df.columns if not str(c).startswith('_')]]

def align_headers(df, expected, source):
    """Dopasowuje naglowki wejsciowe do oczekiwanych nazw niezaleznie od wielkosci liter
    i zbednych spacji (np. 'Status pacjenta' vs 'Status Pacjenta'). Ostrzega o brakach."""
    lut = {str(c).strip().lower(): c for c in df.columns}
    rename = {}
    for name in expected:
        real = lut.get(name.strip().lower())
        if real is not None and real != name:
            rename[real] = name
    if rename:
        df = df.rename(columns=rename)
    missing = [n for n in expected if n not in df.columns]
    if missing:
        log(f"   [UWAGA] {source}: nie znaleziono kolumn (sprawdz naglowki CSV): {missing}")
    return df


# ==========================================
# PRZYGOTOWANIE DANYCH
# ==========================================
def prepare_aa(df):
    """Dodaje kolumny pomocnicze i (w razie potrzeby) rozdziela imie/nazwisko z Kontrahenci.Nazwa."""
    df = align_headers(df.copy(), AA_ALL_COLS, 'AA')
    n = len(df)

    # Rozdzielenie imienia i nazwiska, jesli brak gotowych osobnych kolumn
    have_split = (AA_IMIE in df.columns and AA_NAZWISKO in df.columns
                  and df[AA_IMIE].astype(str).str.strip().ne('').any())
    if not have_split:
        base = df[AA_NAZWA] if AA_NAZWA in df.columns else _empty_series(n)
        base = base.fillna('').astype(str).str.strip()
        split = base.str.split(n=1, expand=True)
        df[AA_IMIE] = split[0].fillna('') if split.shape[1] >= 1 else ''
        df[AA_NAZWISKO] = split[1].fillna('') if split.shape[1] >= 2 else ''

    full = (df[AA_IMIE].fillna('').astype(str) + ' ' + df[AA_NAZWISKO].fillna('').astype(str)).str.strip()
    df['_full']   = norm_name(full)
    df['_pesel']  = norm_pesel(df[AA_PESEL])   if AA_PESEL   in df.columns else _empty_series(n)
    df['_telkom'] = norm_phone(df[AA_TEL_KOM]) if AA_TEL_KOM in df.columns else _empty_series(n)
    df['_teldom'] = norm_phone(df[AA_TEL_STAC]) if AA_TEL_STAC in df.columns else _empty_series(n)
    df['_email']  = norm_email(df[AA_EMAIL])   if AA_EMAIL   in df.columns else pd.Series([''] * n)
    df['_nip']    = norm_nip(df[AA_NIP])        if AA_NIP     in df.columns else _empty_series(n)
    df['_kod']    = df[AA_KOD].fillna('').astype(str).str.strip() if AA_KOD in df.columns else pd.Series([''] * n)
    df['_strato'] = norm_id(df[AA_STRATO])     if AA_STRATO  in df.columns else pd.Series([''] * n)
    df['_id']     = ['AA_' + str(i) for i in range(n)]
    return df

def prepare_st(df):
    """Dodaje kolumny pomocnicze dla bazy Strato."""
    df = align_headers(df.copy(), ST_ALL_COLS, 'Strato')
    n = len(df)
    imie = df[ST_IMIE].fillna('').astype(str) if ST_IMIE in df.columns else pd.Series([''] * n)
    nazw = df[ST_NAZWISKO].fillna('').astype(str) if ST_NAZWISKO in df.columns else pd.Series([''] * n)
    full = (imie + ' ' + nazw).str.strip()
    df['_full']   = norm_name(full)
    df['_pesel']  = norm_pesel(df[ST_PESEL])   if ST_PESEL   in df.columns else _empty_series(n)
    df['_telkom'] = norm_phone(df[ST_TEL_KOM]) if ST_TEL_KOM in df.columns else _empty_series(n)
    df['_teldom'] = norm_phone(df[ST_TEL_DOM]) if ST_TEL_DOM in df.columns else _empty_series(n)
    df['_email']  = norm_email(df[ST_EMAIL])   if ST_EMAIL   in df.columns else pd.Series([''] * n)
    df['_nr']     = norm_id(df[ST_NR])         if ST_NR      in df.columns else pd.Series([''] * n)
    df['_id']     = ['STR_' + str(i) for i in range(n)]
    return df


# ==========================================
# TRASH - odfiltrowanie smieci
# ==========================================
def split_trash(df, source):
    """Rekord = smiec, gdy nazwa jest martwa I wszystkie kontakty (tel/email) sa martwe."""
    n = len(df)
    garbage_pattern = '|'.join(GARBAGE_KEYWORDS)

    def dead(col_help):
        s = df[col_help].fillna('').astype(str).str.strip().str.lower()
        return s.isin(['', 'nan', 'none', 'nat']) | s.str.match(r'^0+$', na=False) | s.str.contains(garbage_pattern, na=False)

    dead_name = dead('_full')
    dead_kom  = dead('_telkom')
    dead_dom  = dead('_teldom')
    dead_mail = dead('_email')

    trash_mask = dead_name & dead_kom & dead_dom & dead_mail
    trash_df = df[trash_mask].copy()
    if not trash_df.empty:
        trash_df['_Source'] = source
    clean_df = df[~trash_mask].copy()
    return clean_df, trash_df


def split_inactive(df, status_col, source, active_values):
    """Oddziela pacjentow nieaktywnych. Aktywny = status ma jedna z wartosci active_values
    (porownanie ignoruje wielkosc liter); kazda inna wartosc (w tym pusta) = nieaktywny."""
    if status_col not in df.columns:
        return df, df.head(0).copy()
    st = df[status_col].fillna('').astype(str).str.replace(r'\.0$', '', regex=True).str.strip().str.lower()
    active_vals = [str(v).strip().lower() for v in active_values]
    active_mask = st.isin(active_vals)
    inactive_df = df[~active_mask].copy()
    if not inactive_df.empty:
        inactive_df['_Source'] = source
    return df[active_mask].copy(), inactive_df


# ==========================================
# PLIK 4 - izolacja biznesu
# ==========================================
def is_business_mask(df):
    """Biznes = NIP niepusty LUB Grupa != pacjenci LUB nazwa wyglada na firme (heurystyka)."""
    n = len(df)
    mask = pd.Series([False] * n, index=df.index)

    # 1. Poprawny NIP -> jednoznacznie biznes (walidacja suma kontrolna w norm_nip)
    if '_nip' in df.columns:
        mask = mask | df['_nip'].notna()

    # 2. Podatnik VAT = 1 lub Forma prawna = 1 -> dzialalnosc gospodarcza
    for col in [AA_VAT, AA_FORMA]:
        if col in df.columns:
            v = df[col].fillna('').astype(str).str.replace(r'\.0$', '', regex=True).str.strip()
            mask = mask | (v == '1')

    # 3. Grupa inna niz pacjenci
    if AA_GRUPA in df.columns:
        grupa = df[AA_GRUPA].astype(str).str.strip().str.upper()
        mask = mask | (grupa != GRUPA_PATIENT.upper())

    # 4. Heurystyka: nazwa zawiera slowa-klucze firmowe
    kw = '|'.join(k.replace('.', r'\.') for k in BUSINESS_KEYWORDS)
    name_l = df['_full'].fillna('').astype(str)
    mask = mask | name_l.str.contains(kw, na=False, regex=True)

    return mask


# ==========================================
# BUDOWA PAR KANDYDATOW (rdzen: Nazwa + identyfikator)
# ==========================================
def build_candidate_pairs(aa, st):
    """Zwraca pary (AA, Strato) majace wspolny co najmniej jeden identyfikator
    (PESEL / Tel. kom. / Tel. dom. / Email) wraz z wynikiem dopasowania nazwy."""
    frames = []
    labels = {'_pesel': 'PESEL', '_telkom': 'Tel.kom', '_teldom': 'Tel.dom', '_email': 'Email'}
    for key in ['_pesel', '_telkom', '_teldom', '_email']:
        a = aa[['_id', key]].copy()
        a = a[a[key].notna() & (a[key].astype(str).str.strip() != '')]
        a = a.rename(columns={key: '_k', '_id': '_id_aa'})
        s = st[['_id', key]].copy()
        s = s[s[key].notna() & (s[key].astype(str).str.strip() != '')]
        s = s.rename(columns={key: '_k', '_id': '_id_st'})
        if a.empty or s.empty:
            log(f"     - {labels[key]}: 0 par")
            continue

        # Ochrona: pomijamy wartosci-placeholdery (zbyt czesto powtarzalne) po obu stronach
        if MAX_KEY_OCCURRENCES:
            bad = set(a['_k'].value_counts().loc[lambda c: c > MAX_KEY_OCCURRENCES].index) \
                | set(s['_k'].value_counts().loc[lambda c: c > MAX_KEY_OCCURRENCES].index)
            if bad:
                a = a[~a['_k'].isin(bad)]
                s = s[~s['_k'].isin(bad)]
                log(f"     - {labels[key]}: pominieto {len(bad)} placeholderow (zbyt czestych wartosci)")
            if a.empty or s.empty:
                log(f"     - {labels[key]}: 0 par")
                continue

        m = a.merge(s, on='_k')[['_id_aa', '_id_st']]
        log(f"     - {labels[key]}: {len(m)} par")
        frames.append(m)

    if not frames:
        return pd.DataFrame(columns=['_id_aa', '_id_st', '_kod', '_strato', '_nr', 'score'])

    pairs = pd.concat(frames, ignore_index=True).drop_duplicates()
    log(f"     - unikalnych par do porownania nazw: {len(pairs)}")
    pairs = pairs.merge(
        aa[['_id', '_kod', '_strato', '_full']].rename(columns={'_id': '_id_aa', '_full': '_full_aa'}),
        on='_id_aa')
    pairs = pairs.merge(
        st[['_id', '_nr', '_full']].rename(columns={'_id': '_id_st', '_full': '_full_st'}),
        on='_id_st')
    # Szybciej niz apply(axis=1): iterujemy po dwoch kolumnach naraz
    pairs['score'] = [fuzzy_score(a, b) for a, b in zip(pairs['_full_aa'], pairs['_full_st'])]
    return pairs


def pairs_to_full_rows(pair_df, aa, st):
    """Buduje pelne wiersze (dane AA + dane Strato) dla podanych par identyfikatorow wewnetrznych."""
    if pair_df is None or pair_df.empty:
        return pd.DataFrame()
    m = pair_df[['_id_aa', '_id_st']].merge(aa, left_on='_id_aa', right_on='_id')
    m = m.merge(st, left_on='_id_st', right_on='_id', suffixes=('_AA', '_Strato'))
    return drop_internal(m).reset_index(drop=True)


def enrich_action(items, aa, st):
    """Buduje wiersze dla Plikow 1/2/3: pierwsze dwie kolumny to Kod AA i Nr Strato,
    a dalej wszystkie dane pacjenta AA oraz (jesli jest) powiazanego pacjenta Strato.
    items: lista dict z kluczami _aid, _sid (moze byc None), 'Kod AA', 'Nr Strato'."""
    cols_first = ['Kod AA', 'Nr Strato']
    if not items:
        return pd.DataFrame(columns=cols_first)
    base = pd.DataFrame(items)
    m = base.merge(aa, left_on='_aid', right_on='_id', how='left')
    m = m.merge(st, left_on='_sid', right_on='_id', how='left', suffixes=('_AA', '_Strato'))
    m = drop_internal(m)
    ordered = cols_first + [c for c in m.columns if c not in cols_first]
    return m[ordered].reset_index(drop=True)


# ==========================================
# KLASYFIKACJA -> 6 plikow
# ==========================================
def classify(aa_patients, st_patients):
    log("   5a. Budowanie par-kandydatow (wspolny identyfikator) i porownanie nazw...")
    pairs = build_candidate_pairs(aa_patients, st_patients)

    empty2 = pd.DataFrame(columns=['Kod AA', 'Nr Strato'])
    result = {
        'file1': empty2.copy(), 'file2': empty2.copy(), 'file3': empty2.copy(),
        'file5': pd.DataFrame(), 'file6': pd.DataFrame(),
    }

    aa_kod    = dict(zip(aa_patients['_id'], aa_patients['_kod']))
    aa_strato = dict(zip(aa_patients['_id'], aa_patients['_strato']))
    valid_nr  = set(st_patients['_nr']) - {''}

    no_strato_ids   = set(aa_patients[aa_patients['_strato'] == '']['_id'])
    with_strato_ids = set(aa_patients[aa_patients['_strato'] != '']['_id'])
    log(f"   5b. Pacjenci AA bez Nr Strato: {len(no_strato_ids)} | z Nr Strato: {len(with_strato_ids)}")

    confident = pairs[pairs['score'] == NAME_EXACT] if not pairs.empty else pairs
    fuzzy_band = pairs[(pairs['score'] >= NAME_FUZZY_MIN) & (pairs['score'] < NAME_EXACT)] if not pairs.empty else pairs

    # ---------- PLIK 1 + PLIK 5 (pacjenci AA bez Nr Strato) ----------
    log("   5c. Tworzenie Plikow 1 i 5 (pacjenci bez Nr Strato)...")
    file1_items, file1_aa_ids = [], set()
    if not confident.empty:
        conf_ns = confident[confident['_id_aa'].isin(no_strato_ids)]
        st_conf_count = conf_ns.groupby('_id_st')['_id_aa'].nunique().to_dict()
        for aa_id, grp in conf_ns.groupby('_id_aa'):
            st_ids = grp['_id_st'].unique()
            if len(st_ids) == 1 and st_conf_count.get(st_ids[0], 0) == 1:
                row = grp.iloc[0]
                file1_items.append({'_aid': aa_id, '_sid': row['_id_st'],
                                    'Kod AA': aa_kod.get(aa_id, ''), 'Nr Strato': row['_nr']})
                file1_aa_ids.add(aa_id)
    result['file1'] = enrich_action(file1_items, aa_patients, st_patients)

    # Plik 5: bez Nr Strato, pasuja po kryteriach (score >= 90), ale nie sa pewnym 1:1 z Pliku 1
    if not pairs.empty:
        f5 = pairs[(pairs['_id_aa'].isin(no_strato_ids)) &
                   (pairs['score'] >= NAME_FUZZY_MIN) &
                   (~pairs['_id_aa'].isin(file1_aa_ids))]
        result['file5'] = pairs_to_full_rows(f5, aa_patients, st_patients)

    # ---------- PLIK 6 + wykrycie blednych polaczen (pacjenci AA z Nr Strato) ----------
    log("   5d. Sprawdzanie istniejacych polaczen (Plik 6) i wykrywanie blednych (Pliki 2/3)...")
    aa_ws = aa_patients[aa_patients['_id'].isin(with_strato_ids)][['_id', '_strato', '_full']] \
        .rename(columns={'_id': 'aa_id', '_full': 'aa_full'})
    st_small = st_patients[['_id', '_nr', '_full']].rename(columns={'_id': 'st_id', '_full': 'st_full'})
    linked = aa_ws.merge(st_small, left_on='_strato', right_on='_nr')  # tylko istniejace numery
    if not linked.empty:
        linked['score'] = [fuzzy_score(a, b) for a, b in zip(linked['aa_full'], linked['st_full'])]
        best = linked.groupby('aa_id')['score'].max().to_dict()
    else:
        best = {}

    # Plik 6: istniejace polaczenie z fuzzy nazwa 90-99%
    if not linked.empty:
        f6 = linked[(linked['score'] >= NAME_FUZZY_MIN) & (linked['score'] < NAME_EXACT)][['aa_id', 'st_id']] \
            .rename(columns={'aa_id': '_id_aa', 'st_id': '_id_st'})
        result['file6'] = pairs_to_full_rows(f6, aa_patients, st_patients)

    # Bledne polaczenie: numer nie istnieje w Strato LUB istnieje, ale nazwa nie zgadza sie DOKLADNIE 100%
    # (pliki sa niezaleznymi filtrami - ten sam rekord moze trafic do Pliku 2, 3 oraz 6 jednoczesnie)
    incorrect_ids = set(i for i in with_strato_ids if aa_strato.get(i, '') not in valid_nr)
    incorrect_ids |= set(aa_id for aa_id, sc in best.items() if sc < NAME_EXACT)

    # Mapa Nr Strato -> wewnetrzne id rekordu Strato (do dolaczenia danych do Plikow 2/3)
    nr_to_stid = {}
    for sid, nr in zip(st_patients['_id'], st_patients['_nr']):
        if nr and nr not in nr_to_stid:
            nr_to_stid[nr] = sid

    # Szukanie zamiennika: pewne dopasowanie (100% + identyfikator) do INNEGO Nr Strato
    file2_items, file3_items = [], []
    if not confident.empty:
        repl = confident[confident['_id_aa'].isin(incorrect_ids) &
                         (confident['_nr'] != confident['_strato'])]
        repl = repl.sort_values('_id_st').drop_duplicates('_id_aa')
        for _, row in repl.iterrows():
            file3_items.append({'_aid': row['_id_aa'], '_sid': row['_id_st'],
                                'Kod AA': aa_kod.get(row['_id_aa'], ''), 'Nr Strato': row['_nr']})

    # Plik 2 = WSZYSTKIE bledne polaczenia (usun stary numer); Plik 3 to podzbior z zamiennikiem.
    # Do Pliku 2 dolaczamy dane blednie powiazanego pacjenta Strato, jesli stary numer istnieje w Strato.
    for aa_id in incorrect_ids:
        old_nr = aa_strato.get(aa_id, '')
        file2_items.append({'_aid': aa_id, '_sid': nr_to_stid.get(old_nr),
                            'Kod AA': aa_kod.get(aa_id, ''), 'Nr Strato': old_nr})

    result['file2'] = enrich_action(file2_items, aa_patients, st_patients)
    result['file3'] = enrich_action(file3_items, aa_patients, st_patients)

    log(f"   5e. Gotowe. Plik1={len(result['file1'])}, Plik2={len(result['file2'])}, "
        f"Plik3={len(result['file3'])}, Plik5={len(result['file5'])}, Plik6={len(result['file6'])}")
    return result


# ==========================================
# ZAPIS
# ==========================================
def save_to_csv_folder(dataframes_dict, folder_name):
    if not os.path.exists(folder_name):
        os.makedirs(folder_name)
    for name, df in dataframes_dict.items():
        path = os.path.join(folder_name, f"{name}.csv")
        if df is None:
            df = pd.DataFrame()
        df.to_csv(path, index=False, sep=';', encoding='utf-8-sig')
        log(f"[OK] Zapisano: {path} ({len(df)} wierszy)")


# ==========================================
# GLOWNY PROCES
# ==========================================
def main(path_aa, path_strato, output_folder):
    log("1. Wczytywanie danych...")
    df_aa_raw = pd.read_csv(path_aa, sep=';', encoding='utf-8', dtype=str)
    df_st_raw = pd.read_csv(path_strato, sep=';', encoding='utf-8', dtype=str)
    init_aa, init_st = len(df_aa_raw), len(df_st_raw)
    log(f"   Wczytano: AA = {init_aa} wierszy, Strato = {init_st} wierszy")

    log("2. Przygotowanie i normalizacja...")
    df_aa = prepare_aa(df_aa_raw)
    df_st = prepare_st(df_st_raw)

    log(f"3. Odfiltrowanie smieci (TRASH), przelacznik = {FILTER_TRASH}...")
    if FILTER_TRASH:
        df_aa, trash_aa = split_trash(df_aa, 'AA')
        df_st, trash_st = split_trash(df_st, 'Strato')
        trash_all = pd.concat([drop_internal(trash_aa), drop_internal(trash_st)], ignore_index=True)
        log(f"   Smieci: {len(trash_all)} | zostalo: AA = {len(df_aa)}, Strato = {len(df_st)}")
    else:
        trash_all = pd.DataFrame()

    log(f"3b. Odfiltrowanie nieaktywnych, przelacznik = {FILTER_INACTIVE}...")
    if FILTER_INACTIVE:
        df_aa, inact_aa = split_inactive(df_aa, AA_STATUS, 'AA', AA_ACTIVE_STATUS_VALUES)
        df_st, inact_st = split_inactive(df_st, ST_STATUS, 'Strato', ST_ACTIVE_STATUS_VALUES)
        inactive_all = pd.concat([drop_internal(inact_aa), drop_internal(inact_st)], ignore_index=True)
        log(f"   Nieaktywni: {len(inactive_all)} | zostalo: AA = {len(df_aa)}, Strato = {len(df_st)}")
    else:
        inactive_all = pd.DataFrame()

    log("4. Plik 4: izolacja dzialalnosci gospodarczych...")
    b_mask = is_business_mask(df_aa)
    business_df = drop_internal(df_aa[b_mask].copy())
    aa_patients = df_aa[~b_mask].copy()
    log(f"   Biznesy: {len(business_df)} | pacjenci AA do dopasowania: {len(aa_patients)}")

    log(f"5. Klasyfikacja pacjentow (Missing Connection), pacjentow AA = {len(aa_patients)}, Strato = {len(df_st)}...")
    res = classify(aa_patients, df_st)

    log("6. Podsumowanie...")
    stats = [
        {'Plik': 'Wejscie AA',   'Liczba wierszy': init_aa},
        {'Plik': 'Wejscie Strato', 'Liczba wierszy': init_st},
        {'Plik': 'Plik1_Dodaj_NrStrato',      'Liczba wierszy': len(res['file1'])},
        {'Plik': 'Plik2_Usun_NrStrato',       'Liczba wierszy': len(res['file2'])},
        {'Plik': 'Plik3_Usun_i_Dodaj_NrStrato', 'Liczba wierszy': len(res['file3'])},
        {'Plik': 'Plik4_Biznesy',             'Liczba wierszy': len(business_df)},
        {'Plik': 'Plik5_Kandydaci_Niepewni',  'Liczba wierszy': len(res['file5'])},
        {'Plik': 'Plik6_Nazwy_Do_Sprawdzenia', 'Liczba wierszy': len(res['file6'])},
        {'Plik': 'TRASH',                     'Liczba wierszy': len(trash_all)},
        {'Plik': 'Nieaktywni',                'Liczba wierszy': len(inactive_all)},
    ]
    df_summary = pd.DataFrame(stats)

    log(f"7. Zapis wynikow do folderu: {output_folder}...")
    export = {
        'Podsumowanie': df_summary,
        '4T_Plik1_Dodaj_NrStrato': res['file1'],
        '4T_Plik2_Usun_NrStrato': res['file2'],
        '4T_Plik3_Usun_i_Dodaj_NrStrato': res['file3'],
        'AUD_Plik4_Biznesy': business_df,
        'AUD_Plik5_Kandydaci_Niepewni': res['file5'],
        'AUD_Plik6_Nazwy_Do_Sprawdzenia': res['file6'],
        'TRASH': trash_all,
        'Nieaktywni': inactive_all,
    }
    save_to_csv_folder(export, output_folder)
    log("Zakonczono pomyslnie.")


if __name__ == '__main__':
    p_aa  = sys.argv[1] if len(sys.argv) > 1 else 'AA.csv'
    p_st  = sys.argv[2] if len(sys.argv) > 2 else 'Strato.csv'
    p_out = sys.argv[3] if len(sys.argv) > 3 else 'Wyniki_Merger3'
    main(p_aa, p_st, p_out)
