# gera uma vez
curl -s -X POST http://localhost:3001/dri -H 'Content-Type: application/json' \
  -d '{"sexo":"F","idade":30,"altura_cm":163,"peso_kg":62,"atividade":"pouco_ativo"}' > /tmp/dri_f.json

# agora explora à vontade
jq 'keys' /tmp/dri_f.json
jq '.' /tmp/dri_f.json
jq '.metas_dia | keys' /tmp/dri_f.json
jq '.metas_dia.energia' /tmp/dri_f.json    # ajuste o nome quando descobrir