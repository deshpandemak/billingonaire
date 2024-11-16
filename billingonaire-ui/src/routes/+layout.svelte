<script>
	import '../app.css';
	import { onMount } from 'svelte';
	import { auth, getUserRole } from '$lib/firebase';
	import { onAuthStateChanged, signOut } from 'firebase/auth';
	import { goto } from '$app/navigation';

	let userEmail = '';
	let userRole = '';

	onMount(() => {
		onAuthStateChanged(auth, async (user) => {
			if (user) {
				console.log('User is authenticated:', user);
				userEmail = user.email;
				userRole = await getUserRole(user);
				console.log('User role:', userRole);
			} else {
				console.log('User is not authenticated');
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
		<div>Billingonaire</div>
		<div class="user-email">{userEmail}</div>
		<button on:click={logout}>Logout</button>
	</header>

	<nav class="nav">
		<ul>
				{#if userRole === 'admin'}
				<li><a href="/upload">Upload Board</a></li>
				{/if}
				<li><a href="/table">Search Board</a></li>
		</ul>
	</nav>

	<main class="main">
		<slot />
	</main>

	<footer class="footer">
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

	.header {
		background-color: #f8f8f8;
		border-bottom: 1px solid #ccc;
	}

	.header a {
		color: #333;
		text-decoration: none;
	}

	.header a:hover {
		text-decoration: underline;
	}

	.header .user-email {
		color: #666;
	}

	.nav {
		background-color: #f8f8f8;
		border-bottom: 1px solid #ccc;
	}

	.nav ul {
		list-style: none;
		padding: 0;
		margin: 0;
		display: flex;
	}

	.nav li {
		margin-right: 1rem;
	}

	.nav a {
		color: #333;
		text-decoration: none;
	}

	.nav a:hover {
		text-decoration: underline;
	}

	.main {
		padding: 2rem;
		background-color: #fff;
		border: 1px solid #ccc;
		border-radius: 4px;
		box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
	}

	.footer {
		background-color: #f8f8f8;
		border-top: 1px solid #ccc;
		padding: 1rem;
		text-align: center;
	}

	.footer p {
		margin: 0;
		color: #666;
	}

	.header,
	.nav,
	.main,
	.footer {
		display: flex;
		justify-content: center;
		align-items: center;
	}

	.header {
		flex-direction: row;
	}

	.nav {
		flex-direction: row;
	}

	.main {
		flex-direction: column;
	}

	.footer {
		flex-direction: column;
	}
</style>
