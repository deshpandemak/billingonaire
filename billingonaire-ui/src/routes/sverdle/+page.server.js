import { fail } from '@sveltejs/kit';
import { Game } from './game';
import { logger } from './logger'; // Import logger

export const load = ({ cookies }) => {
	const game = new Game(cookies.get('sverdle'));

	return {
		/**
		 * The player's guessed words so far
		 */
		guesses: game.guesses,

		/**
		 * An array of strings like '__x_c' corresponding to the guesses, where 'x' means
		 * an exact match, and 'c' means a close match (right letter, wrong place)
		 */
		answers: game.answers,

		/**
		 * The correct answer, revealed if the game is over
		 */
		answer: game.answers.length >= 6 ? game.answer : null
	};
};

export const actions = {
	/**
	 * Modify game state in reaction to a keypress. If client-side JavaScript
	 * is available, this will happen in the browser instead of here
	 */
	update: async ({ request, cookies }) => {
		const game = new Game(cookies.get('sverdle'));

		const data = await request.formData();
		const key = data.get('key');

		const i = game.answers.length;

		if (key === 'backspace') {
			game.guesses[i] = game.guesses[i].slice(0, -1);
		} else {
			game.guesses[i] += key;
		}

		logger.info(`Game state updated: ${game.guesses[i]}`); // Log game state update

		try {
			cookies.set('sverdle', game.toString(), { path: '/' });
		} catch (error) {
			logger.error('Failed to set cookie in update action', error); // Log error
			throw error;
		}
	},

	/**
	 * Modify game state in reaction to a guessed word. This logic always runs on
	 * the server, so that people can't cheat by peeking at the JavaScript
	 */
	enter: async ({ request, cookies }) => {
		const game = new Game(cookies.get('sverdle'));

		const data = await request.formData();
		const guess = (data.getAll('guess'));

		if (!game.enter(guess)) {
			logger.warn(`Invalid guess: ${guess}`); // Log invalid guess
			return fail(400, { badGuess: true });
		}

		logger.info(`Guessed word entered: ${guess}`); // Log guessed word

		try {
			cookies.set('sverdle', game.toString(), { path: '/' });
		} catch (error) {
			logger.error('Failed to set cookie in enter action', error); // Log error
			throw error;
		}
	},

	restart: async ({ cookies }) => {
		cookies.delete('sverdle', { path: '/' });
	}
};
