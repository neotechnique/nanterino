# Changements de comportement du graphe livré — lot G1 (2026-11-02)

Graphe : `nanterino/graph.yaml` (graphe par défaut) + textes des sous-groupes (`nanterino/graph_layout.py`).
Référence des traces : `tests/brain-trace-baseline.json` (avant G1 : `tests/golden/brain-trace-baseline.pre-g1.json`).

## Le bug corrigé

Robot sourd (micro forcé fermé) : un vrai visage le sortait de la veille (`visage` + `auto_greet_on_face`),
puis il restait pour toujours en `relance`. Le délai de clôture
(`after: silence_cloture_s, since: last_speech, when: mic_active`) ne peut pas compter quand le micro reste fermé,
et aucune autre règle ne fait sortir de `relance` sans parole.

Deux corrections, chacune vérifiée par une mutation (règle retirée -> `test_deaf_never_traps` échoue) :

1. **Veille, visage, robot sourd : pas d'accueil automatique.** Le robot n'entendrait pas la réponse. Il écrit
   seulement une note au journal. Les deux règles forment une seule condition si/sinon `is_deaf` dans l'éditeur
   (sous-groupe « Réveil »). Le bouton Démarrer et la question tapée marchent toujours en mode sourd, pour les essais.
2. **Relance, micro fermé : clôture quand même.** Nouvelle règle `after: silence_cloture_s, since: state,
   when: [not mic_active, not_speaking]` : note au journal, notification au tableau de bord, puis `cloture` (motif
   `micro_ferme`). Elle couvre le mode sourd, et aussi un micro qui ne s'ouvre pas. `since: state` compte depuis
   l'entrée en relance, et `not_speaking` évite de couper la phrase de relance. En usage normal, le micro se rouvre
   à `relance_done`, bien avant ce délai, donc la règle ne s'applique pas.

Pourquoi les deux : la première évite la conversation inutile, la seconde garantit qu'aucun chemin (bouton
Démarrer, question tapée, mode sourd activé en pleine conversation, micro en panne) ne reste bloqué.

## Scénarios de trace existants (71 au total, 68 avant G1)

Aucune trace existante n'a changé : `trace parity: 71 scenarios, 0 different` et `compiled-graph parity 71/71`.
Les 68 scénarios d'origine tournent avec `deaf: False`, et dans ces cas la règle « micro fermé » ne s'applique pas
(le micro se rouvre après 0,1 s de relance, le délai de test est de 3 s). Les notes de journal ajoutées
(`log_note`) n'apparaissent pas dans les traces.

| Scénario | Avant -> après | Pourquoi |
|---|---|---|
| les 68 scénarios d'origine | identique -> identique | robot pas sourd ; rien ne change |

## Nouveaux scénarios (ajoutés à la référence après relecture, chacun exécuté deux fois avec un résultat identique)

| Scénario | Trace attendue | Pourquoi |
|---|---|---|
| `deaf_face_ignored_in_veille` | aucun `go` ; fin en veille | visage + robot sourd : pas d'accueil (correction 1) |
| `deaf_start_returns_to_veille` | veille -> accueil -> ecoute -> relance (silence) -> cloture (`micro_ferme`) -> veille | bouton Démarrer en mode sourd : la relance se termine quand même (correction 2) |
| `deaf_question_then_silence` | ... -> reponse -> ecoute -> relance -> cloture (`micro_ferme`) -> veille | une question tapée en mode sourd reçoit sa réponse, puis le robot revient en veille |

Test supplémentaire `test_deaf_never_traps` (pas une trace) : en mode sourd et sans aucune entrée, le robot revient
en veille en moins de 12 s depuis chaque état de conversation (veille après Démarrer, accueil, ecoute, reponse,
relance, cloture ; mesuré entre 0,4 et 2,4 s avec des délais courts). Un visage vu ensuite le laisse en veille.
`eteint` est exclu exprès : c'est l'interrupteur de l'opérateur, et seuls « on » ou « start » en sortent.

## Autres changements visibles

- `max_turns` (ecoute et relance) : une note au journal « Nombre maximal d'échanges atteint » après le passage en
  clôture. La trace ne change pas.
- Post-its : « Réveil » (colonne veille) indique « sauf robot sourd », et « Silence -> clôture » indique « ou micro
  fermé, robot sourd ».
- Numéros de chaînes dans le journal : la chaîne d'accueil sur visage passe de `veille/t0` à `veille/t1`, et
  Démarrer passe de `veille/t1` à `veille/t2`, parce que la note pour le robot sourd est insérée avant.

## Nouveaux nœuds proposés mais non utilisés (choix volontaires)

- `visage_perdu` reste **désactivé**. La vision le poste après 10 s sans visage. Or, pendant une écoute, un
  visiteur qui regarde ailleurs ou qui se penche vers le tableau de bord perd souvent la détection : le robot dirait
  au revoir au milieu d'une question. Les délais de silence (8 + 15 s) ferment déjà une pièce vide. C'est aussi
  l'exemple `enabled: false` livré dans l'éditeur, et trois tests ainsi que l'aide s'appuient dessus.
- Accueil varié (`say_random` / `salutations`) : non retenu. `say_random` sur une liste vide (modifiable dans
  l'éditeur) ne dit rien et n'envoie pas `say_done` : le robot resterait bloqué en accueil. De plus, le texte
  d'accueil appartient à `config.json` (tableau de bord, voix pré-calculée) : une liste du graphe l'écraserait sans
  que l'opérateur le voie. Enfin, le tirage aléatoire rendrait les traces non déterministes.
- `conversation_started` / `conversation_ended` / `turn_counted` : le graphe n'a aucun compteur fait à la main à
  remplacer (tours et réparations sont des compteurs système). Les ajouter ne changerait rien au comportement.
- `is_question` / `utterance_contains` : les intentions (`appel`, `au_revoir`, `chanson`, sinon question) suffisent.
  Exiger « ? » ou un mot interrogatif ferait ignorer des demandes à l'impératif (« Montre-moi le parc »).

## Re-référence

Les 3 nouvelles traces ont été fusionnées dans `tests/brain-trace-baseline.json` (aucune trace existante n'a été
réécrite), et la version précédente est gardée dans `tests/golden/brain-trace-baseline.pre-g1.json`. La méthode est
décrite dans l'en-tête de `tests/test_brain_graph.py`.

## Tests adaptés (avec la raison)

- `test_brain_graph.test_invalid_graphs_rejected` : la garde du visage est maintenant une liste (texte remplacé
  mis à jour).
- `test_brain_graph.H` : le démarrage n'attend plus la ligne « mic on » quand `deaf=True` (un robot sourd n'ouvre
  jamais son micro).
- `test_graph_vars.test_if_else_is_one_condition` : 5 sorties Faux au lieu de 4 (`veille is_deaf`). Une condition
  niée isolée est attendue (`relance not mic_active`, sans jumelle positive sur le même déclencheur).
- `test_graph_visual.test_sharing_lighter_and_equivalent` : la borne absolue passe de 0,76 × 182 à 0,76 × 198 nœuds
  (le dessin hérité du graphe livré a grandi). Le même ratio de 76 % est toujours vérifié.
- `test_graph_features` (journal, simulateur) : numéros de chaînes `veille/t1` -> `veille/t2` et `veille/t0` ->
  `veille/t1`.
- Web `canvas` (wires) : 5 fils Faux et une seule condition niée isolée.
- Web `tester` : les étapes simulées commencent par `start` au lieu de `visage`, parce que le Testeur simule avec la
  configuration réelle du robot (sourd en ce moment), qui n'accueille donc plus un visage.
- Web `diag` et `human` (point rouge sur la mini-carte) : le déclencheur de test est placé à 520 px de la condition
  au lieu de 260 px. Le graphe plus grand réduit l'échelle de la mini-carte, et le point rouge du déclencheur
  (l'erreur cite les deux nœuds) recouvrait le pixel testé de la condition.
