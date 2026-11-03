# Changements de comportement du graphe livré — lot G2 (2026-11-02)

Graphe : `nanterino/graph.yaml` (graphe par défaut) + sous-groupes et post-its (`nanterino/graph_layout.py`).
Référence des traces : `tests/brain-trace-baseline.json` (avant G2 : `tests/golden/brain-trace-baseline.pre-g2.json`).

But : utiliser davantage les nouveaux nœuds pour un comportement plus riche, sans rien casser de G1 (le robot sourd ne
reste jamais bloqué hors veille).

## Ce qui change

1. **Salutations variées.** L'accueil ne dit plus toujours la même phrase. La salutation part du déclencheur
   « Une conversation commence » (`conversation_started`, posté par le robot à chaque sortie de veille ou d'éteint),
   dans l'état accueil :
   - un visiteur seul, choix 1 : la phrase d'accueil de `config.json` (`greeting`, modifiable au tableau de bord) ;
   - un visiteur seul, choix 2 : une phrase de la liste `salutations` (3 phrases, sac mélangé : pas de répétition
     avant d'avoir tout dit).
   Le choix est la variable `choix_salutation` (1 ou 2) : elle vaut 1 au démarrage (la première salutation est donc
   toujours celle de la configuration) et elle est tirée au hasard à la fin de chaque conversation (règle globale sur
   `conversation_ended`, action « Choisir au hasard »). La phrase de la configuration garde donc tout son rôle : elle
   est dite une fois sur deux en moyenne, et toujours au premier visiteur.
2. **Plusieurs personnes.** S'il y a au moins 2 visages au début de la conversation (`face_count_compare >= 2`), le
   robot dit une phrase pour le groupe (liste `salutations_groupe`, 2 phrases, sac mélangé), par exemple « Bonjour à
   vous tous, bienvenue ! ». L'une d'elles demande de parler une personne à la fois (la reconnaissance vocale suit mal
   deux voix).
3. **Horaires d'ouverture.** En veille, un visage hors des horaires d'ouverture (`dans_les_horaires` faux) ne
   déclenche plus l'accueil automatique : une note au journal seulement. Le bouton Démarrer et « Nanterino » saluent
   toujours. La clé `opening_hours` est vide par défaut, et vide veut dire « toujours ouvert » : **rien ne change tant
   que l'opérateur n'a pas écrit d'horaires**.
4. **Secours de l'accueil.** Nouvelle règle de l'accueil : si rien n'a terminé la salutation après
   `silence_cloture_s` (15 s) depuis l'entrée en accueil et que le robot ne parle pas, note au journal (warning) puis
   écoute (motif `accueil_secours`). Le graphe livré ne s'en sert jamais (tout passage en accueil vient de veille ou
   d'éteint, donc d'un début de conversation, et chaque salutation se termine, même avec une liste vide, depuis L27).
   Elle protège un graphe modifié dans l'éditeur qui ferait entrer en accueil depuis un autre état.

## Pourquoi cette forme

- La salutation ne peut plus être dans `on_enter` : `on_enter` est une suite d'actions, sans condition. Le choix
  (groupe, phrase de la configuration, phrase variée) se fait donc sur `conversation_started`, traité juste après
  l'entrée en accueil (même boucle, pas de délai perceptible).
- Les trois branches sont un si/sinon imbriqué avec des conditions pures. Le moteur exécute **toutes** les règles
  sans `to` qui s'appliquent : avec `random_chance` (tirage à chaque règle), deux salutations pouvaient partir ensemble
  ou aucune (vu dans un premier essai : « greeting » puis une phrase variée dans la même conversation). Le tirage se
  fait donc à la fin de la conversation précédente, dans une variable.
- Toutes les phrases des deux listes sont calculées à l'avance au chargement du graphe (`graph.say_texts` lit les
  listes de `say_random`) ; la phrase de la configuration l'était déjà.
- Traces reproductibles : le harnais des traces fixe maintenant la graine du hasard du robot (`brain.rng.seed(0)`,
  comme le simulateur de l'éditeur). Chaque scénario a été exécuté deux fois : fichiers identiques.

## Scénarios de trace existants (71)

Aucune trace existante n'a changé : les 71 scénarios d'avant G2 donnent la même trace (premier visiteur après le
démarrage = phrase de la configuration, `choix_salutation` vaut 1 ; aucun scénario n'a 2 visages ni d'horaires).

| Scénario | Avant -> après | Pourquoi |
|---|---|---|
| les 71 scénarios d'avant G2 | identique -> identique | première salutation = phrase de la configuration ; pas de groupe ; pas d'horaires |

## Nouveaux scénarios (4, ajoutés à la référence après relecture, exécutés deux fois, identiques)

| Scénario | Trace attendue | Pourquoi |
|---|---|---|
| `g2_greetings_vary` | 9 conversations (Démarrer puis Stop) : `greeting`, S-a, S-b, S-c, S-a, S-c, `greeting`, `greeting`, S-b | salutations variées : la phrase de la configuration d'abord, puis le tirage ; le sac ne répète pas une phrase avant d'avoir dit les 3 |
| `g2_group_greeting` | 2 visages, visage -> accueil -> « Bonjour à vous tous, bienvenue ! … » -> ecoute (`say_done`) | salutation de groupe |
| `g2_face_outside_hours` | horaires 09:00-18:00, horloge fixée à 20 h : visage -> aucun `go`, reste en veille ; Démarrer -> accueil -> `greeting` -> ecoute | hors horaires : pas d'accueil automatique, Démarrer marche toujours |
| `g2_face_inside_hours` | mêmes horaires, horloge fixée à 10 h : visage -> accueil -> `greeting` -> ecoute | dans les horaires : comportement d'avant |

(S-a = « Bonjour ! Je suis Nanterino, le robot de Nanterre… », S-b = « Bonjour et bienvenue ! Moi, c'est Nanterino… »,
S-c = « Bonjour ! Ravi de vous voir… ».) Les scénarios d'horaires fixent l'horloge murale du robot : ils ne dépendent
pas de l'heure réelle.

## Tests sans trace

- `test_deaf_never_traps` : un cas en plus, « groupe » (2 visages + Démarrer, robot sourd) : retour en veille.
- `test_g2_greeting_never_traps` (nouveau) : (a) accueil forcé depuis l'écoute, sans début de conversation : la règle
  de secours fait passer en écoute (motif `accueil_secours`) ; (b) liste `salutations` vidée : la salutation se
  termine quand même (`say_done`) ; (c) groupe, robot sourd : retour en veille ; (d) visage hors horaires : reste en
  veille, puis Démarrer marche.

## Propositions non retenues (avec la raison)

- **Réaction au premier tour** (petite phrase avant la première réponse) : non. Elle passerait avant la réponse
  (une phrase de 1 à 2 s ajoutée au délai de la première réponse, le chemin le plus sensible à la latence), ou en même
  temps que la réponse (deux voix). **Relance différente au premier silence** : non plus. La phrase de relance vient
  de `speak_relance` (texte de la configuration, ou phrase « répétez » préparée) ; aucune action ne prépare un autre
  texte, et déplacer la relance hors de `on_enter` toucherait la réparation « pas compris », sans gain net pour G2.
- **`personnes_multiples` en veille** : non utilisé. Le robot le poste après 1 s avec 2 visages, donc après
  l'événement `visage` du premier visage : en veille, l'accueil est déjà parti. La salutation de groupe lit donc le
  nombre de visages au début de la conversation (`face_count_compare`).
- **Message « fermé » sur Démarrer** : non. Démarrer est le bouton de l'opérateur (essais, démonstration) et doit
  toujours marcher ; de même « Nanterino » dit par une personne présente.
- **`ouverture` / `fermeture`** : pas de règle. En veille, il n'y a rien à faire au changement d'horaire (la condition
  lit l'horaire à chaque visage) ; couper une conversation en cours à la fermeture serait impoli.
- **`conversation_ended` -> note de résumé au journal** : non. Le journal du robot note déjà chaque transition ; la
  règle `conversation_ended` sert au tirage de la salutation suivante.
- **`is_question`** : non, même raison qu'en G1 (les demandes à l'impératif seraient ignorées).

## Autres changements visibles

- Notes au journal : « Visage vu hors des horaires d'ouverture : pas d'accueil automatique. » (info) et, si le secours
  sert, « Accueil sans salutation terminée : passage en écoute. » (warning).
- Éditeur, colonne accueil : sous-groupes « Entrée » (micro coupé), « Salutation » (le si/sinon), « Fin de
  salutation » (`greeting_done` et `say_done`), « Secours ». Règles globales : sous-groupe « Fin de conversation ».
  Post-it « Réveil » (veille) : « sauf robot sourd ou hors des horaires d'ouverture ».
- Variables : `choix_salutation` (entier 1..2, 1 au démarrage), listes `salutations` (phrases remplacées : les
  anciennes « Bonjour ! », « Bonjour, bienvenue ! », « Bonjour, je suis Nanterino. » étaient un exemple non dit) et
  `salutations_groupe` (nouvelle).
- Numéros de chaînes : en veille, l'accueil sur visage reste `veille/t1` ; la note hors horaires est `veille/t2`,
  donc Démarrer passe de `veille/t2` à `veille/t3`, « Nanterino » de `t3` à `t4`, la question tapée de `t4` à `t5`.
  En accueil, `greeting_done` passe de `accueil/t0` à `accueil/t3`.

## Preuves par mutation (graphe mutant via `NANTERINO_TEST_GRAPH`, chacune fait échouer un test G2)

| Mutant | Test qui échoue |
|---|---|
| visage salue sans regarder les horaires (`dans_les_horaires` retiré) | trace `g2_face_outside_hours` (le robot passe en accueil à 20 h) |
| branche groupe jamais vraie (`count: 99` dans la première règle seulement) | trace `g2_group_greeting` : aucune salutation, le secours passe en écoute (`accueil_secours`) — montre aussi que le secours rattrape un si/sinon incomplet |
| groupe salué avec la liste `salutations` | trace `g2_group_greeting` (phrase d'un visiteur seul) |
| règle de secours désactivée | `test_g2_greeting_never_traps` (a) : le robot reste en accueil |

## Tests adaptés (avec la raison)

- `test_brain_graph.H` : graine fixe du hasard du robot (`rng.seed(0)`) ; `test_invalid_graphs_rejected` : texte
  remplacé mis à jour (garde du visage + `dans_les_horaires`).
- `test_graph_vars.test_if_else_is_one_condition` : 8 sorties Faux au lieu de 5 (veille horaires, accueil nombre de
  visages, accueil `choix_salutation`) ; `test_simulator_returns_vars_per_step` : liste `salutations_groupe` en plus.
- `test_graph_vars2.test_default_graph_examples_do_not_change_behaviour` : `salutations` et `salutations_groupe` sont
  maintenant dites par l'accueil (les autres exemples restent inutilisés).
- `test_graph_visual` : listes attendues (+ `salutations_groupe`), sous-groupes attendus (accueil : Entrée,
  Salutation, Fin de salutation, Secours ; globales : + Fin de conversation), borne absolue du dessin compact 0,76 ×
  233 nœuds au lieu de 0,76 × 198 (même ratio de 76 %).
- `test_graph_features` : numéros de chaînes (`veille/t2` -> `veille/t3`, `accueil/t0` -> `accueil/t3`).
- `test_nodes_n2.test_shipped_graph_uses_no_n2_node` : le graphe livré utilise maintenant exactement
  `conversation_started`, `conversation_ended` et `face_count_compare` (G2 validé par l'utilisateur), et aucun autre
  nœud N2.
- `test_nodes_registry.test_missing_condition_or_trigger_breaks_golden` : le déclencheur retiré par la mutation passe
  de `say_done` (utilisé par le graphe livré depuis G2, qui ne se chargerait plus) à `media_finished`.
- Références de vocabulaire `tests/golden/vocab-default-graph*.json` (5 fichiers) : seules les données du graphe
  livré changent (bloc `variables` : `choix_salutation`, `salutations`, `salutations_groupe` ; choix des
  `list_ref`). Les versions `pre-m4/m5/n1/n2` reçoivent la même modification, avec leurs clés d'époque.
- Web `canvas` : 8 fils Faux au lieu de 5.

## Re-référence

Les 4 nouvelles traces ont été fusionnées dans `tests/brain-trace-baseline.json` (aucune trace existante réécrite ;
le fichier ne fait que s'allonger), la version précédente est gardée dans
`tests/golden/brain-trace-baseline.pre-g2.json`.
