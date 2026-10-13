-- Requêtes reproductibles sur l'historique des runs (F5).
-- Exécution : python -m filets query analysis/queries.sql  (ou tout client SQLite : DB Browser, DBeaver…)
;

-- 1. Comparaison des configurations à la dernière saison : stock, indice de norme, coût
SELECT label, mode, COUNT(*) AS runs,
       ROUND(AVG(stock_ratio), 3) AS stock_moyen,
       ROUND(AVG(norm_index), 3)  AS norme_moyenne,
       ROUND(AVG(llm_calls), 0)   AS appels_llm
FROM v_season_indicators v
WHERE season = (SELECT MAX(season) FROM v_season_indicators w WHERE w.run_id = v.run_id)
GROUP BY label, mode ORDER BY label, mode;

-- 2. Trajectoire du stock saison par saison, par configuration (pour les courbes du rapport)
SELECT label, season, ROUND(AVG(stock_ratio), 3) AS stock, ROUND(AVG(norm_index), 3) AS norme,
       COUNT(*) AS runs
FROM v_season_indicators GROUP BY label, season ORDER BY label, season;

-- 3. Écart entre ce qui est promis et ce qui est pêché, par archétype
SELECT json_extract(a.value, '$.archetype') AS archetype,
       COUNT(*) AS promesses, ROUND(AVG(p.kept), 2) AS taux_tenues,
       ROUND(AVG(p.landed - p.promised), 2) AS ecart_moyen_t
FROM v_promises p
JOIN events s ON s.run_id = p.run_id AND s.type = 'run_start', json_each(json_extract(s.payload, '$.agents')) a
WHERE json_extract(a.value, '$.id') = p.agent
GROUP BY archetype;

-- 4. Incidents des agents LLM par type et par modèle (A4, O2)
SELECT i.incident_type, c.tier, COUNT(*) AS n
FROM v_incidents i LEFT JOIN (SELECT DISTINCT run_id, agent, tier FROM v_llm_calls) c
  ON c.run_id = i.run_id AND c.agent = i.agent
GROUP BY i.incident_type, c.tier ORDER BY n DESC;

-- 5. Coût par run (E4) : appels, tokens, latence cumulée, par niveau de modèle
SELECT run_id, tier, COUNT(*) AS appels, SUM(prompt_tokens + completion_tokens) AS tokens,
       ROUND(SUM(latency_s), 1) AS latence_s
FROM v_llm_calls GROUP BY run_id, tier ORDER BY run_id, tier;

-- 6. Traçabilité (F6) : les événements bruts derrière un indicateur de fin de saison
SELECT e.type, e.sim_time, e.actor, e.payload
FROM indicators i, json_each(i.source_event_ids) src
JOIN events e ON e.event_id = src.value
WHERE i.run_id = (SELECT run_id FROM runs LIMIT 1) AND i.trigger = 'season_end' AND i.season = 2;

-- 7. Ce qui s'est dit juste avant l'adoption d'une règle (B4)
SELECT n.run_id, n.season, n.quota, u.speaker, u.round, u.text
FROM v_norms n JOIN v_utterances u ON u.run_id = n.run_id AND u.season = n.season AND u.sim_time <= n.sim_time
ORDER BY n.run_id, n.season, u.sim_time;
