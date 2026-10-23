"""Static configuration: which indices to track and where NSE keeps the files."""

from __future__ import annotations

import datetime as dt

# How far back the first (backfill) run goes. Two years gives enough history
# for 200-day averages, 52-week highs and a weekly Relative Rotation Graph.
BACKFILL_START = dt.date(2024, 10, 1)

ARCHIVE = "https://nsearchives.nseindia.com"
INDEX_CLOSE_URL = ARCHIVE + "/content/indices/ind_close_all_{ddmmyyyy}.csv"
BHAVCOPY_URL = ARCHIVE + "/products/content/sec_bhavdata_full_{ddmmyyyy}.csv"
CONSTITUENT_URLS = [
    ARCHIVE + "/content/indices/{slug}.csv",
    "https://www.niftyindices.com/IndexConstituent/{slug}.csv",
]
FNO_LOTS_URL = ARCHIVE + "/content/fo/fo_mktlots.csv"

# Stock series kept from the bhavcopy (EQ = normal, BE = trade-for-trade).
STOCK_SERIES = {"EQ", "BE"}

# key: short id used everywhere in the tool
# name: display name; aliases: how the index may be spelled in NSE's
# all-indices file (matched case-insensitively); slugs: constituent file
# names to try, in order.
BENCHMARKS = [
    {"key": "NIFTY50", "name": "Nifty 50", "aliases": ["Nifty 50"],
     "slugs": ["ind_nifty50list"]},
    {"key": "NIFTY500", "name": "Nifty 500", "aliases": ["Nifty 500"],
     "slugs": ["ind_nifty500list"]},
    # Broadest universe (Nifty 500 + Microcap 250); used only to decide
    # which stocks to store.
    {"key": "TOTALMKT", "name": "Nifty Total Market",
     "aliases": ["Nifty Total Market"],
     "slugs": ["ind_niftytotalmarket_list", "ind_niftytotalmarketlist"]},
]

SECTORS = [
    # ---- Sectoral indices ----
    {"key": "AUTO", "name": "Auto", "group": "Sectoral",
     "aliases": ["Nifty Auto"], "slugs": ["ind_niftyautolist"]},
    {"key": "BANK", "name": "Bank", "group": "Sectoral",
     "aliases": ["Nifty Bank"], "slugs": ["ind_niftybanklist"]},
    {"key": "FINSERV", "name": "Financial Services", "group": "Sectoral",
     "aliases": ["Nifty Financial Services"], "slugs": ["ind_niftyfinancelist"]},
    {"key": "FMCG", "name": "FMCG", "group": "Sectoral",
     "aliases": ["Nifty FMCG"], "slugs": ["ind_niftyfmcglist"]},
    {"key": "HEALTHCARE", "name": "Healthcare", "group": "Sectoral",
     "aliases": ["Nifty Healthcare Index", "Nifty Healthcare"],
     "slugs": ["ind_niftyhealthcarelist"]},
    {"key": "IT", "name": "IT", "group": "Sectoral",
     "aliases": ["Nifty IT"], "slugs": ["ind_niftyitlist"]},
    {"key": "MEDIA", "name": "Media", "group": "Sectoral",
     "aliases": ["Nifty Media"], "slugs": ["ind_niftymedialist"]},
    {"key": "METAL", "name": "Metal", "group": "Sectoral",
     "aliases": ["Nifty Metal"], "slugs": ["ind_niftymetallist"]},
    {"key": "PHARMA", "name": "Pharma", "group": "Sectoral",
     "aliases": ["Nifty Pharma"], "slugs": ["ind_niftypharmalist"]},
    {"key": "PVTBANK", "name": "Private Bank", "group": "Sectoral",
     "aliases": ["Nifty Private Bank"],
     "slugs": ["ind_nifty_privatebanklist", "ind_niftyprivatebanklist"]},
    {"key": "PSUBANK", "name": "PSU Bank", "group": "Sectoral",
     "aliases": ["Nifty PSU Bank"], "slugs": ["ind_niftypsubanklist"]},
    {"key": "REALTY", "name": "Realty", "group": "Sectoral",
     "aliases": ["Nifty Realty"], "slugs": ["ind_niftyrealtylist"]},
    {"key": "CONSDUR", "name": "Consumer Durables", "group": "Sectoral",
     "aliases": ["Nifty Consumer Durables"],
     "slugs": ["ind_niftyconsumerdurableslist"]},
    {"key": "OILGAS", "name": "Oil & Gas", "group": "Sectoral",
     "aliases": ["Nifty Oil & Gas", "Nifty Oil and Gas"],
     "slugs": ["ind_niftyoilgaslist"]},
    {"key": "CHEMICALS", "name": "Chemicals", "group": "Sectoral",
     "aliases": ["Nifty Chemicals"],
     "slugs": ["ind_niftychemicals_list", "ind_niftyChemicals_list"]},
    # ---- Thematic indices ----
    {"key": "ENERGY", "name": "Energy", "group": "Thematic",
     "aliases": ["Nifty Energy"], "slugs": ["ind_niftyenergylist"]},
    {"key": "INFRA", "name": "Infrastructure", "group": "Thematic",
     "aliases": ["Nifty Infrastructure", "Nifty Infra"],
     "slugs": ["ind_niftyinfralist"]},
    {"key": "PSE", "name": "PSE", "group": "Thematic",
     "aliases": ["Nifty PSE"], "slugs": ["ind_niftypselist"]},
    {"key": "CPSE", "name": "CPSE", "group": "Thematic",
     "aliases": ["Nifty CPSE"], "slugs": ["ind_niftycpselist"]},
    {"key": "COMMODITIES", "name": "Commodities", "group": "Thematic",
     "aliases": ["Nifty Commodities"], "slugs": ["ind_niftycommoditieslist"]},
    {"key": "CONSUMPTION", "name": "India Consumption", "group": "Thematic",
     "aliases": ["Nifty India Consumption", "Nifty Consumption"],
     "slugs": ["ind_niftyconsumptionlist"]},
    {"key": "MNC", "name": "MNC", "group": "Thematic",
     "aliases": ["Nifty MNC"], "slugs": ["ind_niftymnclist"]},
    {"key": "DEFENCE", "name": "India Defence", "group": "Thematic",
     "aliases": ["Nifty India Defence"],
     "slugs": ["ind_niftyindiadefence_list", "ind_niftyindiadefencelist"]},
    {"key": "CAPMKT", "name": "Capital Markets", "group": "Thematic",
     "aliases": ["Nifty Capital Markets"],
     "slugs": ["ind_niftycapitalmarkets_list", "ind_niftycapitalmarketslist"]},
    {"key": "MFG", "name": "India Manufacturing", "group": "Thematic",
     "aliases": ["Nifty India Manufacturing"],
     "slugs": ["ind_niftyindiamanufacturing_list", "ind_niftyindiamanufacturinglist"]},
    {"key": "HOUSING", "name": "Housing", "group": "Thematic",
     "aliases": ["Nifty Housing"],
     "slugs": ["ind_niftyhousing_list", "ind_niftyhousinglist"]},
    {"key": "DIGITAL", "name": "India Digital", "group": "Thematic",
     "aliases": ["Nifty India Digital"],
     "slugs": ["ind_niftyindiadigital_list", "ind_niftyindiadigitallist"]},
    {"key": "TOURISM", "name": "India Tourism", "group": "Thematic",
     "aliases": ["Nifty India Tourism"],
     "slugs": ["ind_niftyindiatourism_list", "ind_niftyindiatourismlist"]},
]

ALL_INDICES = BENCHMARKS + SECTORS
