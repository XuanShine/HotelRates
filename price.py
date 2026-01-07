#!/usr/bin/env python
# coding: utf-8

# TODO: utiliser les prix des avions, les recherches google, les flux événements de l'office du tourisme de Grasse
# TODO: tester les "maj"
# TODO: fixer les chemins relatifs
# TODO: permettre la configuration du PACE aisément
# TODO:
# Concepte de booking curve (selon l'historique des réservations)
# Scrape les disponibilités des concurrents et stocker
# Scrape les prix des concurrents et stocker"""


# Taux de remplissage: Faible, Moyen, Fort, Critique

# Montée en charge
# Pace (Matrice des seuils)

"""Phase 1 : Le Socle (J-90 et plus)
​Objectif : Assurer une base de sécurité (couvrir les coûts fixes).
​Si "Faible" : On ne panique pas, c'est trop tôt. On maintient les prix publics, on ouvre les promotions "Early Bird" (Réservez tôt, moins cher, non remboursable).
​Si "Fort" (> 40%) : Attention ! Vous vendez trop vite et trop peu cher. Action : Augmentez le prix de base (+15%) et fermez les tarifs "Corporate" ou "Groop" bon marché.
​Phase 2 : Le Yielding Actif (J-21 à J-60)
​Objectif : Optimiser le prix moyen. C'est là que le vrai jeu commence.
​Si "Faible" (Retard) : Il faut stimuler. Lancez une "Flash Sale" ou une offre packagée (Chambre + Petit-déj inclus) pour augmenter la valeur perçue sans casser le prix sec.
​Si "Fort" (Avance) : Vous êtes en position de force. Alignez-vous sur le concurrent le plus cher de votre set. Refusez les séjours d'une seule nuit (Minimum Stay 2 nuits) pour optimiser le planning.
​Phase 3 : L'Optimisation Finale (J-0 à J-14)
​Objectif : Remplir les trous ou maximiser la marge pure.
​Si "Faible" (< 60%) : C'est l'alerte rouge. C'est le moment d'ouvrir les vannes sur les OTAs (Booking/Expedia) avec des promos de dernière minute ("Last Minute Deal"). Mieux vaut vendre à -20% que de laisser la chambre vide (tant qu'on est au-dessus du coût variable).
​Si "Critique" (> 90%) : Fermez les canaux de vente coûteux (Booking.com prend 17% de commission). Gardez les dernières chambres uniquement pour votre site web en direct et vendez-les au prix fort ("Rack Rate").

​1. Levier Tarifaire (Le Prix)
​C'est le levier le plus évident, mais attention à ne pas détruire votre image de marque.
​Pour accélérer (Retard) :
​Promotions Opaque : Activez les promos "Mobiles" ou "Genius" sur Booking.com. Cela baisse le prix pour des segments spécifiques sans afficher un prix barré public à tout le monde.
​Offres Packagées : "3 nuits pour le prix de 2" ou "Petit-déjeuner offert". Vous maintenez votre ADR (Prix moyen) facial, mais vous baissez le coût réel pour le client.
​Pour freiner (Avance) :
​Monter le BAR (Best Available Rate) : Augmentez le prix de 10€ à 20€.
​Fermer les tarifs réduits : Bloquez les tarifs "Non Remboursable" (souvent -10%) pour ne laisser que le tarif Flexible (plus cher).
​2. Levier de Restrictions (Inventory Control)
​C'est souvent plus puissant que le prix.
​Pour accélérer (Retard) :
​Lever le MLOS (Minimum Length of Stay) : Si vous imposiez 2 nuits minimum, passez à 1 nuit.
​Accepter le "Samedis isolés" : Souvent, les hôteliers bloquent les arrivées le samedi pour éviter les séjours d'une nuit qui bloquent le week-end. Si vous êtes en retard : ouvrez tout.
​Pour freiner (Avance) :
​Imposer un MLOS : "2 nuits minimum". Cela filtre les clients "parasites" qui prennent juste le samedi soir (et empêchent de vendre le vendredi-samedi).
​CTA (Closed to Arrival) : Interdire d'arriver le jour J, forçant les gens à arriver la veille.
​3. Levier de Distribution (Les Canaux)
​Gérez où vous vendez.
​Pour accélérer (Retard) :
​Ouvrir tous les canaux : Expedia, Booking, HotelTonight (pour le last minute).
​Surcommissionner (Visibility Booster) : Payer 20% de commission au lieu de 17% sur Booking.com pour remonter en haut de page temporairement.
​Pour freiner (Avance) :
​Fermer les OTAs coûteux : Si vous êtes presque complet, fermez Expedia et Booking. Ne gardez que votre Site Web (0% commission) et le téléphone. C'est là que vous faites votre marge nette.

​Une fois que vous avez cette colonne Pickup, vous pouvez affiner votre stratégie :
​Pickup Nul (0) : Calme plat.
​Action : Si ça dure depuis 3 jours \rightarrow Baisse de prix.
​Pickup Positif fort (> 3/jour) : Demande forte soudaine.
​Action : Monter le prix immédiatement pour les chambres restantes.
​Pickup Négatif (Annulations) : Attention.
​Action : Vérifiez si un concurrent n'a pas cassé ses prix, incitant vos clients à annuler pour aller ailleurs.
"""



import sys, os

C = os.path.abspath(os.path.dirname(__file__))

import numpy as np
import pandas as pd
from functools import reduce
from datetime import date
import yaml
import gspread
from gspread_dataframe import get_as_dataframe, set_with_dataframe
from sheet import spreadsheet as ss
import json
from utils import load_df

from loguru import logger

YAML_HOTELS = os.path.join(C, "hotels.yml")

with open(YAML_HOTELS, "r") as f_in:
    HOTELS = yaml.safe_load(f_in)
SHORT_TO_ID = {
    hotel['short']: hotel['id_tripadvisor'] 
    for hotel in HOTELS.values()
}
SHORT_NAMES = [data['short'] for data in HOTELS.values()]
WORKSHEET = ss.client.open("Prix Aroma").worksheet("Feuille1")

def calcul_price(ecart_TO, echelle_a_comparer:list):
    if not echelle_a_comparer:
        raise ValueError("echelle_a_comparer vide")
    echelle_a_comparer = [x for x in echelle_a_comparer if isinstance(x, (int, float))]
    # echelle_a_comparer: prix des concurrent
    ecarts = np.linspace(-25, 15, len(echelle_a_comparer)).tolist()
    prix_conseille = max(45, np.interp(ecart_TO, ecarts, sorted(echelle_a_comparer)))
    return prix_conseille

def calcul_ecart(jours_restants, libre, dispo):
    if dispo == 0:
        return 0
    _, _, _, _, ecart = evaluer_performance_booking(jours_restants, to_actuel=(dispo-libre)/dispo*100)
    return ecart


def evaluer_performance_booking(jours_restants, to_actuel):
    """
    Définit si on est en retard ou en avance selon la date.
    jours_restants : int (ex: 30)
    to_actuel : float (ex: 45.0 pour 45%)
    Lead Time (Jours avant arrivée) TO Cible (Occupancy) Commentaire
    J-90                              10% - 15% Base de contrats corporate / Congrès.
    J-60                              20% - 30% Les organisateurs d'événements.
    J-30                              40% - 50% Le socle est posé.
    J-14                              60% - 70% Accélération forte.
    J-7                               75% - 85% Les déplacements pro se confirment.
    J-3                               85% - 95% Dernières minutes business (Prix fort).
    J-0                               95% - 100% Complet
    """

    # 1. Définition de la courbe idéale (Objectif de remplissage à J-x)
    # À J-90 on veut 15%, à J-30 on veut 40%, à J-0 on veut 95%
    # On utilise l'interpolation pour avoir un chiffre précis pour chaque jour
    x_days =   [90, 60, 30, 14, 7,  3,   0]
    y_target = [10, 20, 40, 60, 75, 85, 95]
    # Équivalent chambres réservées 
    #          [3,  6,  13, 19, 24, 27, 30]

    # Calcul de l'objectif théorique pour aujourd'hui
    target_to = np.interp(jours_restants, x_days[::-1], y_target[::-1])

    # 2. Comparaison (L'écart ou "Pick-up gap")
    ecart = to_actuel - target_to

    # 3. Décision Stratégique
    if ecart < -10:
        statut = "RETARD CRITIQUE"
        action = "Action : Baisser prix / Ouvrir Promos / Flash Sales"
        facteur_prix = -0.10
    elif ecart < -5:
        statut = "Léger Retard"
        action = "Action : S'aligner sur le concurrent le moins cher"
        facteur_prix = -0.05
    elif ecart > 15:
        statut = "AVANCE FORTE"
        action = "Action : Monter prix (+15%) / Restreindre conditions (Non-Remboursable)"
        facteur_prix = +0.15
    elif ecart > 5:
        statut = "Légère Avance"
        action = "Action : Monter prix (+5%)"
        facteur_prix = +0.05
    else:
        statut = "Dans la cible (On Pace)"
        action = "Action : Suivre le marché (Concurrents médians)"
        facteur_prix = 0.0

    return statut, round(target_to, 1), action, facteur_prix, round(ecart, 0)


def calcul_price_df(df):
    now = pd.Timestamp.now().normalize()
    df["ecart_TO"] = df.apply(lambda row: calcul_ecart((row.name-now).days, row["Libre"], row["Dispo"]), axis=1)
    
    # On remplie les prix manquants des concurrents
    df2 = df.copy()
    df2[list(SHORT_NAMES)] = df2[list(SHORT_NAMES)].ffill()

    mask_maj_vide = df2["maj"].isna()
    mask_maj_is_number = pd.to_numeric(df2["maj"], errors="coerce").notna()
    mask_maj_is_list = (df2["maj"].str.startswith("[", na=False)) & (df2["maj"].str.endswith("]", na=False))

    # Calcul du prix pour les lignes sans "maj"
    df2.loc[mask_maj_vide, "Aroma"] = df2[mask_maj_vide].apply(
        lambda row: calcul_price(
            row["ecart_TO"], 
            row[list(SHORT_NAMES)].tolist()
        ), axis=1
    )
    # Calcul du prix pour les lignes avec "maj" nombre: 10 -> +10% -> prix * 1.10
    df2.loc[mask_maj_is_number, "Aroma"] = df2[mask_maj_is_number].apply(
        lambda row: (1 + pd.to_numeric(row["maj"]) / 100) * calcul_price(
            row["ecart_TO"], 
            row[list(SHORT_NAMES)].tolist()
        ), axis=1
    )

    # Calcul du prix pour les lignes avec "maj" liste: [75, 100, 150] -> ignore le prix des concurrents, utilise la liste à la place.
    df2.loc[mask_maj_is_list, "Aroma"] = df2[mask_maj_is_list].apply(
        lambda row: calcul_price(
            row["ecart_TO"], 
            json.loads(row["maj"])
        ), axis=1
    )
    
    df["Aroma"] = df2["Aroma"]
    return df



def export_price(df):
    headers = WORKSHEET.row_values(1)
    EXPORT_HEADERS = ["Aroma", "ecart_TO"]
    for header in EXPORT_HEADERS:
        try:
            col_index = headers.index(header) + 1
        except ValueError:
            print(f"Column {header} not found in the Sheet!")
            continue
        df_subset = df[[header]]
        set_with_dataframe(
            WORKSHEET, 
            df_subset, 
            row=1, 
            col=col_index, 
            include_index=False, 
            resize=False
        )


if __name__ == "__main__":
    sheet_key = "10vet57RQGSTB2SLOLhwJPehER9nU6gixURsYHv6NULU"
    df = load_df(sheet_key)
    calcul_price_df(df)
    export_price(df)


