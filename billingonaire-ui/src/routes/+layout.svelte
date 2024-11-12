<script>
	import '../app.css';
	import { onMount } from 'svelte';
	import { auth } from '$lib/firebase';
	import { onAuthStateChanged, signOut } from 'firebase/auth';
	import { goto } from '$app/navigation';

	onMount(() => {
		onAuthStateChanged(auth, (user) => {
			if (!user) {
				goto('/login');
			}
		});
	});

	const logout = async () => {
		try {
			await signOut(auth);
			goto('/login');
		} catch (error) {
			console.error('Logout failed', error);
		}
	};
</script>

<div class="app">
	<header class="header">
		Billingonaire
		<button on:click={logout}>Logout</button>
	</header>

	<nav>
		<ul>
			<li><a href="/upload">Upload Board</a></li>
			<li><a href="/table">Search Board</a></li>
		</ul>
	</nav>

	<main>
		<slot />
	</main>

	<footer>
		<p>© billingonaire</p>
	</footer>
</div>

<style>
	.app {
		display: flex;
		flex-direction: column;
		min-height: 100vh;
	}

	main {
		flex: 1;
		display: flex;
		flex-direction: column;
		padding: 1rem;
		width: 100%;
		max-width: 64rem;
		margin: 0 auto;
		box-sizing: border-box;
	}

	footer {
		display: flex;
		flex-direction: column;
		justify-content: center;
		align-items: center;
		padding: 12px;
	}

	footer a {
		font-weight: bold;
	}

	@media (min-width: 480px) {
		footer {
			padding: 12px 0;
		}
	}
</style>
