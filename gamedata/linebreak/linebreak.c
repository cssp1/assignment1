/* Break long lines in a JavaScript file, without changing its meaning at all. */
/* This should work identically to linebreak.py, just a lot faster. */

/* Copyright (c) 2015 SpinPunch. All rights reserved.
   Use of this source code is governed by an MIT-style license that can be
   found in the LICENSE file. */

#include <stdio.h>
#include <ctype.h>

enum State {
	NORMAL, QUOTE, QUOTE_SPECIALCHAR, SYMBOL, NUMBER
};

int main(int argc, char *argv[]) {
	static const int limit = 500; /* max output length (strings may break this) */
	enum State state = NORMAL;
	int len = 0; /* length of current line of output */
	int ends_with_linebreak = 0; /* true iff last character written was a linebreak */

	while(1) {
		char c = fgetc(stdin);
		if(c == EOF) { break; }

		if(state == NORMAL && len >= limit) {
			fputc('\n', stdout);
			len = 0;
			ends_with_linebreak = 1;
		}

		/* skip any non-significant whitespace from the input */
		if(state == NORMAL && isspace(c)) { continue; }

		/* write to output */
		fputc(c, stdout);
		len += 1;
		ends_with_linebreak = (c == '\n' ? 1 : 0);

		switch(state) {
		case NORMAL:
			if(c == '"') {
				state = QUOTE;
			} else if(isalpha(c)) {
				state = SYMBOL;
			} else if(isdigit(c) || c == '.') {
				state = NUMBER;
			}
			break;
		case SYMBOL:
			if(!isalpha(c)) {
				state = NORMAL;
			}
			break;
		case NUMBER:
			if(!isdigit(c) && c != '.' && c != 'e') {
				state = NORMAL;
			}
			break;
		case QUOTE:
			if(c == '\\') {
				state = QUOTE_SPECIALCHAR;
			} else if(c == '"') {
				state = NORMAL;
			}
			break;
		case QUOTE_SPECIALCHAR:
			state = QUOTE;
			break;
		}
	}
	if(state != NORMAL) {
		fprintf(stderr, "ended in non-normal state\n");
		return 1;
	}

	/* ensure the file ends with a (single) linebreak, even if source did not */
	if(!ends_with_linebreak) {
		fputc('\n', stdout);
	}

	return 0;
}
