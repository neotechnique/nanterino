# Changements de comportement du graphe livré — lot G3 (2026-11-02)

Graphe : `nanterino/graph.yaml` (graphe par défaut) + sous-groupes et post-its (`nanterino/graph_layout.py`).
Code : `nanterino/nodes/actions/log_state.py` (bilan : visiteurs et erreurs), `nanterino/brain.py` (garde le jour
terminé pour le bilan de minuit, 3 lignes).
Référence des traces : `tests/brain-trace-baseline.json` (avant G3 : `tests/golden/brain-trace-baseline.pre-g3.json`).
Copie Drive (texte complet, même contenu) : `projects/jetson-robot/nanterino/Notes/behaviour-changes-G3.md`.

## Ce qui change

1. **Visiteur parti.** Écoute : plus aucun visage depuis 20 s (`no_face_since`) -> la relance attend ; à 11 s de
   silence, au revoir (motif `visiteur_parti`, note). Un visage revient -> relance tout de suite. Relance (micro
   rouvert) : même règle, au revoir à 11 s au lieu de 15 s. 11 s > `max_utterance_s` (10) + 0,8 s : personne ne parle.
   Gardes `not_busy`, `not_speaking`, et en relance `mic_active`. Seuils = constantes du graphe. `visage_perdu` reste
   désactivé (il ne regarde pas le silence ; exemple de l'éditeur, 3 tests).
2. **Voix et relance.** `Brain._on_speech_start` remet déjà `last_speech` à zéro : pas de règle `voice_detected`
   (double comptage). Nouveau : la clôture sur silence de la relance attend la fin d'une transcription (`not_busy`).
3. **Bruit fort** (écoute, relance) : note + chrono de silence remis à zéro, 2 fois au plus par conversation
   (`bruits_forts`, max 2, `var_at_bound`) ; ensuite seulement une note. Un bruit par seconde : veille quand même.
4. **Bilan au journal** : `log_state` chaque heure (sauf minuit) ; à minuit note « Nouveau jour » + `log_state`. La
   ligne porte `visiteurs_jour`, `visiteurs_veille`, `erreurs_24h`, `avertissements_24h`. Jamais de texte du visiteur.
5. **Trop de « pas compris »** : à `reparations = max_reparations`, phrase d'aide (`say_text`, pré-calculée), micro
   coupé puis rouvert à `say_done` (+ `reset_silence`) ; ensuite silencieux. Écoute et relance.
6. **Durcissement G1** : la règle « micro fermé » demande `robot_quiet_since >= 1` (fenêtre fin de phrase -> événement).

## Scénarios existants (75 avant G3)

| Scénario | Avant -> après | Pourquoi |
|---|---|---|
| `not_understood_x3` | 3e « euh » : rien -> micro coupé, phrase d'aide, micro rouvert | idée 5 (voulu) |
| les 74 autres | identique -> identique | aucun visage absent 20 s, bruit ou transcription au moment d'un délai |

## Nouveaux scénarios (deux exécutions identiques)

`g3_visitor_left_in_ecoute`, `g3_face_back_relances`, `g3_visitor_left_in_relance`, `g3_visitor_talking_is_not_cut`,
`g3_relance_voice_restarts_delay`, `g3_relance_waits_transcription`, `g3_loud_noise_bounded`, `g3_journal_summary`,
`g3_repair_help_in_relance`, `g3_repair_help_in_ecoute`. Nouveau test `test_g3_never_traps` (sourd sans visage depuis
chaque état ; aide coupée par « tais-toi » ; bruit chaque seconde ; après l'aide sans rien d'autre).

## Mutations : 14/14 tuées

1a garde visage de la relance, 1b `not_busy` visiteur parti, 1c visiteur parti en relance, 2a `not_busy` clôture de
relance, 2b délai compté depuis l'état, 3a bruit sans borne (`test_g3_never_traps`), 3b règle du bruit, 4a bilan de
minuit, 4b bilan horaire à minuit, 4c `brain.py` oublie la veille, 4d `log_state` sans visiteurs, 5a pas d'aide,
5b aide à chaque fois, 5c micro jamais rouvert.

## Tests adaptés

`test_nodes_n3` (`test_shipped_graph_uses_only_g3_n3_nodes`, champs de `log_state`), `test_graph_visual`
(`SUBGROUPS_WANTED`, borne 0,76 × 301, dessin « aller à » 32 croisements max, dessin des variables = 0),
`test_graph_vars` (11 Faux, 3 conditions niées isolées), `test_graph_features` (`ecoute/t2`, simulateur sans visage ->
`visiteur_parti`), `test_nodes_registry` (module retiré : `show_text`), goldens vocab (+ variable `bruits_forts` dans les
copies `pre-*` comme en G2), `run_graph_tests.sh` (400 -> 700 s par suite).
