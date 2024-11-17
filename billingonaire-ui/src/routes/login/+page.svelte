<script>
  import { onMount } from 'svelte';
  import { auth } from '$lib/firebase';
  import { signInWithEmailAndPassword } from 'firebase/auth';
  import { goto } from '$app/navigation';

  let email = '';
  let password = '';
  let error = '';

  const login = async () => {
    console.log(`Login attempt for email: ${email}`);
    try {
      await signInWithEmailAndPassword(auth, email, password);
      console.log(`Login successful for email: ${email}`);
      localStorage.setItem('userEmail', email);
      goto('/upload');
    } catch (e) {
      console.error(`Login failed for email: ${email}, error: ${e.message}`);
      error = e.message;
    }
  };
</script>

<svelte:head>
  <title>Login</title>
</svelte:head>

<div class="login-container">
  <h1>Login</h1>
  <form on:submit|preventDefault={login}>
    <div>
      <label for="email">Email</label>
      <input type="email" id="email" bind:value={email} required />
    </div>
    <div>
      <label for="password">Password</label>
      <input type="password" id="password" bind:value={password} required />
    </div>
    {#if error}
      <p class="error">{error}</p>
    {/if}
    <button type="submit">Login</button>
  </form>
</div>

<style>
  .login-container {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    min-height: 50vh;
    max-width: 400px;
    margin: 0 auto;
    padding: 1rem;
    border: 1px solid #ccc;
    border-radius: 4px;
    box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
  }

  .header {
    font-size: 2.5rem;
    font-weight: bold;
    text-align: center;
    margin-bottom: 2rem;
  }

  h1 {
    text-align: center;
  }

  form {
    display: flex;
    flex-direction: column;
  }

  label {
    margin-bottom: 0.5rem;
  }

  input {
    margin-bottom: 1rem;
    padding: 0.5rem;
    border: 1px solid #ccc;
    border-radius: 4px;
  }

  .error {
    color: red;
    margin-bottom: 1rem;
  }

  button {
    padding: 0.5rem;
    border: none;
    border-radius: 4px;
    background-color: #007bff;
    color: white;
    cursor: pointer;
  }

  button:hover {
    background-color: #0056b3;
  }
</style>
