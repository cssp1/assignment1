 #!/bin/sh

# send Gold owed to players who made VAT-taxed purchases January 1
# that were rejected by the server because we did not interpret the
# paid_amount/tax_amount fields correctly.

< logs/20150101-exceptions.txt env grep 'Rejecting unfavorable price.*BUY_GAMEBUCKS' | \
sed 's|.*2015/01|2015/01|; s/ Exception.*by user / /; s/ (.*BUY_GAMEBUCKS_/ /; s/_FBP.*//;' | \
sort -n  | \
awk '{print "./check_player.py", $3, "--give-alloy", $4, "--message-subject", "\"Purchased Gold\"", "--message-body", "\"Here is the Gold from your purchase made on", $1, "at", $2 "\"" }'
