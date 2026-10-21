-- Les requêtes de queries.sql, pour l'historique dans PostgreSQL (JSONB au lieu de JSON1), plus deux requêtes propres
-- à PostgreSQL : coût par système (1 réflexe / 2 réflexion) et recherche directe dans les charges utiles.
-- Exécution : python -m filets query analysis/queries_pg.sql --pg   (ou psql, DBeaver… sur 127.0.0.1:19432)
;

-- 1. Comparaison des configurations à la dernière saison : stock, indice de norme, coût
SELECT label, mode, COUNT(*) AS runs,
       ROUND(AVG(stock_ratio)::numeric, 3) AS stock_moyen,
       ROUND(AVG(norm_index)::numeric, 3)  AS norme_moyenne,
       ROUND(AVG(llm_calls)::numeric, 0)   AS appels_llm
FROM v_season_indicators v
WHERE season = (SELECT MAX(season) FROM v_season_indicators w WHERE w.run_id = v.run_id)
GROUP BY label, mode ORDER BY label, mode;

-- 2. Trajectoire du stock saison par saison, par configuration (pour les courbes du rapport)
SELECT label, season, ROUND(AVG(stock_ratio)::numeric, 3) AS stock, ROUND(AVG(norm_index)::numeric, 3) AS norme,
       COUNT(*) AS runs
FROM v_season_indicators GROUP BY label, season ORDER BY label, season;

-- 3. Écart entre ce qui est promis et ce qui est pêché, par archétype
SELECT a->>'archetype' AS archetype,
       COUNT(*) AS promesses, ROUND(AVG(p.kept::int)::numeric, 2) AS taux_tenues,
       ROUND(AVG(p.landed - p.promised)::numeric, 2) AS ecart_moyen_t
FROM v_promises p
JOIN events s ON s.run_id = p.run_id AND s.type = 'run_start'
CROSS JOIN LATERAL jsonb_array_elements(s.payload->'agents') a
WHERE a->>'id' = p.agent
GROUP BY archetype;

-- 4. Incidents des agents LLM par type et par modèle (A4, O2)
SELECT i.incident_type, c.tier, COUNT(*) AS n
FROM v_incidents i LEFT JOIN (SELECT DISTINCT run_id, agent, tier FROM v_llm_calls) c
  ON c.run_id = i.run_id AND c.agent = i.agent
GROUP BY i.incident_type, c.tier ORDER BY n DESC;

-- 5. Coût par run (E4) : appels, tokens, latence cumulée, par niveau de modèle
SELECT run_id, tier, COUNT(*) AS appels, SUM(prompt_tokens + completion_tokens) AS tokens,
       ROUND(SUM(latency_s)::numeric, 1) AS latence_s
FROM v_llm_calls GROUP BY run_id, tier ORDER BY run_id, tier;

-- 6. Traçabilité (F6) : les événements bruts derrière un indicateur de fin de saison
SELECT e.type, e.sim_time, e.actor, e.payload
FROM indicators i CROSS JOIN LATERAL jsonb_array_elements_text(i.source_event_ids) src
JOIN events e ON e.event_id = src
WHERE i.run_id = (SELECT run_id FROM runs ORDER BY started_at DESC LIMIT 1) AND i.trigger = 'season_end' AND i.season = 2;

-- 7. Ce qui s'est dit juste avant l'adoption d'une règle (B4)
SELECT n.run_id, n.season, n.quota, u.speaker, u.round, u.text
FROM v_norms n JOIN v_utterances u ON u.run_id = n.run_id AND u.season = n.season AND u.sim_time <= n.sim_time
ORDER BY n.run_id, n.season, u.sim_time;

-- 8. Coût par système : réflexes (S1, dont le modèle de décision open) et réflexion (S2)
SELECT run_id, COALESCE(system, '-') AS systeme, model, COUNT(*) AS appels,
       SUM(prompt_tokens + completion_tokens) AS tokens, ROUND(AVG(latency_s)::numeric, 2) AS latence_moy_s
FROM v_llm_calls GROUP BY run_id, system, model ORDER BY run_id, system, model;

-- 9. Les décisions prises par la règle de repli (charges utiles JSONB, index GIN)
SELECT run_id, season, payload->>'agent' AS agent, payload->>'decision_type' AS decision, payload->>'justification' AS pourquoi
FROM events WHERE type = 'decision' AND payload @> '{"fallback": true}' ORDER BY run_id, sim_time;
