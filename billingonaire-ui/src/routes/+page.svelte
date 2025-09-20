<script>
  import { onMount } from 'svelte';
  import { auth } from '../lib/firebase.js';
  import { goto } from '$app/navigation';

  let user = null;

  onMount(() => {
    // Check if user is authenticated
    const unsubscribe = auth.onAuthStateChanged((authUser) => {
      user = authUser;
      if (!authUser) {
        goto('/login');
      }
    });

    return unsubscribe;
  });

  function logout() {
    auth.signOut().then(() => {
      goto('/login');
    });
  }
</script>

<svelte:head>
  <title>Billingonaire</title>
  <meta name="description" content="Billingonaire - Billing Management System" />
</svelte:head>

<section>
  <h1>Welcome to Billingonaire</h1>
  
  {#if user}
    <div class="welcome-content">
      <p>Welcome, {user.email}!</p>
      
      <div class="actions">
        <a href="/upload" class="action-button">Upload PDF</a>
        <a href="/table" class="action-button">View Data</a>
        <a href="/about" class="action-button">About</a>
        <button on:click={logout} class="logout-button">Logout</button>
      </div>
    </div>
  {:else}
    <p>Please wait while we check your authentication...</p>
  {/if}
</section>

<style>
  section {
    display: flex;
    flex-direction: column;
    justify-content: center;
    align-items: center;
    flex: 0.6;
  }

  h1 {
    width: 100%;
  }

  .welcome-content {
    max-width: 600px;
    text-align: center;
  }

  .actions {
    display: flex;
    flex-direction: column;
    gap: 1rem;
    margin-top: 2rem;
  }

  .action-button {
    display: inline-block;
    padding: 1rem 2rem;
    background-color: var(--color-theme-1);
    color: white;
    text-decoration: none;
    border-radius: 4px;
    transition: background-color 0.2s;
  }

  .action-button:hover {
    background-color: var(--color-theme-2);
    text-decoration: none;
  }

  .logout-button {
    padding: 0.5rem 1rem;
    background-color: #666;
    color: white;
    border: none;
    border-radius: 4px;
    cursor: pointer;
    margin-top: 1rem;
  }

  .logout-button:hover {
    background-color: #555;
  }

  @media (min-width: 640px) {
    .actions {
      flex-direction: row;
      justify-content: center;
    }
  }
</style>