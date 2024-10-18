<script>
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';

  let file;
  let dataframe = null;
  let error = '';

  const uploadFile = async () => {
    const formData = new FormData();
    formData.append('file', file);

    try {
      const response = await fetch('http://localhost:8000/upload-pdf', {
        method: 'POST',
        body: formData
      });

      if (!response.ok) {
        throw new Error('Failed to upload file');
      }

      const data = await response.json();
      dataframe = data;
    } catch (e) {
      error = e.message;
    }
  };
</script>

<svelte:head>
  <title>Upload PDF</title>
</svelte:head>

<div class="upload-container">
  <h1>Upload PDF</h1>
  <form on:submit|preventDefault={uploadFile}>
    <div>
      <label for="file">Choose PDF file</label>
      <input type="file" id="file" accept="application/pdf" bind:this={file} required />
    </div>
    {#if error}
      <p class="error">{error}</p>
    {/if}
    <button type="submit">Upload</button>
  </form>

  {#if dataframe}
    <div class="dataframe">
      <h2>Dataframe</h2>
      <pre>{JSON.stringify(dataframe, null, 2)}</pre>
    </div>
  {/if}
</div>

<style>
  .upload-container {
    max-width: 600px;
    margin: 0 auto;
    padding: 1rem;
    border: 1px solid #ccc;
    border-radius: 4px;
    box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
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

  .dataframe {
    margin-top: 1rem;
  }

  pre {
    background-color: #f8f8f8;
    padding: 1rem;
    border-radius: 4px;
    overflow-x: auto;
  }
</style>
