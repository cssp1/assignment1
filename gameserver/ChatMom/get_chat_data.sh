# Get training data from game chat logs and chat reports

GAMES="mf tr mf2 bfm sg dv"

OUT_BAD="/tmp/game-bad.txt"
OUT_GOOD="/tmp/game-good.txt"
OUT_RECENT="/tmp/game-recent.txt"

echo -n "" > "$OUT_BAD"
for GAME in $GAMES; do
    echo "SELECT ch.text
FROM ${GAME}_upcache.${GAME}_chat ch, ${GAME}_upcache.${GAME}_chat_reports rep
WHERE rep.resolution IN ('violate','warn')
AND ch._id = rep.message_id
AND (rep.channel LIKE 'r:%' OR rep.channel IN ('global_english','global_t123'))" | ./mysql.py >> "$OUT_BAD"
done

echo -n "" > "$OUT_GOOD"
for GAME in $GAMES; do
    echo "SELECT ch.text
FROM ${GAME}_upcache.${GAME}_chat ch
WHERE NOT EXISTS(SELECT 1 FROM ${GAME}_upcache.${GAME}_chat_reports rep WHERE rep.message_id = ch._id)
AND (ch.channel LIKE 'r:%' OR ch.channel IN ('global_english','global_t123'))
ORDER BY time DESC LIMIT 10000" | ./mysql.py >> "$OUT_GOOD"
done

echo -n "" > "$OUT_RECENT"
for GAME in tr; do
    echo "SELECT ch.text
FROM ${GAME}_upcache.${GAME}_chat ch
WHERE (ch.channel LIKE 'r:%' OR ch.channel IN ('global_english','global_t123'))
ORDER BY time DESC LIMIT 1000" | ./mysql.py >> "$OUT_RECENT"
done
