/* adapted from https://github.com/SaidinWoT/minesweeper */
/*
 * NCurses Minesweeper with arrow keys!
 */

typedef unsigned int _Bool;

#include <ncurses.h>
#include <stdlib.h>
#include <time.h>
#define ROWS 8 
#define COLS 8
#define MINES 10
#define pair(y,x) game[y][x] % 2 == -1 ? 1 : (game[y][x] < 0 ? 2 : 3)

/*
 *	game array
 *	Tracks values of each square
 *	Squares each maintain a single integer value to indicate their state:
 *	A value of...
 *		0 or greater indicates a checked spot with that number of
 *		mines in the adjacent squares
 *		
 *		-2 indicates an unflagged, unchecked, empty spot
 *
 *		-3 indicates a flagged, unchecked, empty spot
 *
 *		-4 indicates an unflagged, unchecked spot containing a mine
 *
 *		-5 indicates a flagged, unchecked spot containing a mine
 */
int game[ROWS][COLS];
int cursY, cursX;			//Track the current cursor location
int i, j;					//Globally used for coordinate manipulation
int mines, clean, flags;	//Tracking of number of mines, clean spots, and remaining flags, respectively

void printSpot(int row, int col);
int takeTurn();
int checkSpot(int row, int col);
int checkAround(int row, int col, int opt);
void moveCursor();
void endGame();

int main() {
	initscr();
	if(has_colors() == TRUE) {
		start_color();
		init_pair(1, COLOR_BLACK, COLOR_YELLOW);
		init_pair(2, COLOR_WHITE, COLOR_BLUE);
		init_pair(3, COLOR_BLACK, COLOR_CYAN);
		init_pair(4, COLOR_RED, COLOR_CYAN);
		init_pair(5, COLOR_RED, COLOR_YELLOW);
	}
	cbreak();
	keypad(stdscr, TRUE);
	curs_set(0);

	srand(time(0));
	for(i = 0; i < ROWS; i++) {
		for(j = 0; j < COLS; j++) {
			game[i][j] = -2;
			printSpot(i, j);
		}
	}
	//mvchgat(cursY, 3*cursX, 3, A_REVERSE, pair(cursY, cursX), NULL);
	attron(A_REVERSE);
	printSpot(cursY, cursX);
	attroff(A_REVERSE);

	mines=MINES;
	/*
	do {
		mvprintw(ROWS+1, 0, "How many mines would you like? ");
		clrtobot();
		scanw("%2d", &mines);
	} while(mines < 1);
	*/
	noecho();
	flags = mines;
	clean = (ROWS * COLS) - mines;
	mvprintw(ROWS+1, 0, "Flags Remaining: %02d", flags);
	clrtobot();
	mvprintw(ROWS+2, 0, "(move:wasd flag:f step:c quit:q)");
	clrtobot();

	while(takeTurn()) {}
	endGame();
	endwin();

	return 0;
}

void printSpot(int row, int col) {
	attron(COLOR_PAIR(pair(row, col)));
	if(game[row][col] > 0) {
		mvprintw(row, 3*col, "[%d]", game[row][col]);
	} else {
		mvprintw(row, 3*col, game[row][col] % 2 == -1 ? "[F]" : (game[row][col] < 0 ? "[?]" : "   "));
	}
	attroff(COLOR_PAIR(pair(row, col)));
}

int takeTurn() {
	moveCursor();
	if(mines > 0) {
		game[cursY][cursX] -= 2;
		while(mines > 0) {
			i = rand()%ROWS;
			j = rand()%COLS;
			if(game[i][j] > -4) {
				game[i][j] = (game[i][j] % 2) - 4;
				mines--;
			}
		}
		game[cursY][cursX] += 2;
	}
	return checkSpot(cursY, cursX);
}

int checkSpot(int row, int col) {
	if(game[row][col] == -2) {
		game[row][col] = checkAround(row, col, 0);
		if(game[row][col] == 0) {
			checkAround(row, col, 1);
		}
		printSpot(row, col);
		return --clean;
	} else if(game[row][col] > 0 && game[row][col] == checkAround(row, col, 2)) {
		return checkAround(row, col, 3);
	} else if(game[row][col] == -4) {
		return 0;
	}
	return 1;
}

int checkAround(int row, int col, int opt) {
	int y, x, total = 0;
	for(y = row < 1 ? 0 : row - 1; y <= (row == ROWS - 1 ? ROWS - 1 : row + 1); y++) {
		for(x = col < 1 ? 0 : col - 1; x <= (col == COLS - 1 ? COLS - 1 : col + 1); x++) {
			if(opt == 0 && game[y][x] <= -4) {
				total++;
			} else if(opt == 1 && game[y][x] / 2 == -1) {
				checkSpot(y, x);
			} else if(opt == 2 && game[y][x] % 2 == -1) {
				total++;
			} else if(opt == 3 && game[y][x] < 0) {
				total++;
				if(checkSpot(y, x) == 0) {
					return 0;
				}
			}
		}
	}
	return total;
}

void moveCursor() {
	static int ch;
	for(ch = getch(); ch != 'c' && ch != ' ' && ch != '\n'; ch = getch()) {
		//mvchgat(cursY, 3*cursX, 3, A_NORMAL, pair(cursY, cursX), NULL);
		printSpot(cursY, cursX);
		switch(ch) {
			case 'w':
			case 'k':
			case KEY_UP:
				cursY = (cursY + ROWS - 1) % ROWS;
				break;
			case 'a':
			case 'h':
			case KEY_LEFT:
				cursX = (cursX + COLS - 1) % COLS;
				break;
			case 's':
			case 'j':
			case KEY_DOWN:
				cursY = (cursY + ROWS + 1) % ROWS;
				break;
			case 'd':
			case 'l':
			case KEY_RIGHT:
				cursX = (cursX + COLS + 1) % COLS;
				break;
			case 'f':
				if(game[cursY][cursX] % 2 == -1) {
					game[cursY][cursX]++;
					flags++;
				} else if(game[cursY][cursX] < 0 && flags > 0) {
					game[cursY][cursX]--;
					flags--;
				}
				mvprintw(ROWS+1, 17, "%02d", flags);
				printSpot(cursY, cursX);
				break;
			case 'q':
				endwin();
				exit(0);
		}
		//mvchgat(cursY, 3*cursX, 3, A_REVERSE, pair(cursY, cursX), NULL);
		attron(A_REVERSE);
		printSpot(cursY, cursX);
		attroff(A_REVERSE);
	}
}

void endGame() {
	if(clean > 0) {
		for(i = 0; i < ROWS; i++) {
			for(j = 0; j < COLS; j++) {
				if((game[i][j] - 1) / 2 == -2) {
					attron(COLOR_PAIR(game[i][j] == -4 ? 4 : 5));
					mvprintw(i, 3*j, "   ");
					mvaddch(i, (3*j)+1, game[i][j] == -4 ? ACS_DIAMOND : 'X');
					attroff(COLOR_PAIR(game[i][j] == -4 ? 4 : 5));
				}
			}
		}
	}
	attron(COLOR_PAIR(1) | A_BOLD);
	mvprintw(ROWS+1, 0, clean > 0 ? "YOU LOST!" : "EPIC WINZ!");
	attroff(COLOR_PAIR(1) | A_BOLD);
	clrtoeol();
	getch();
}
