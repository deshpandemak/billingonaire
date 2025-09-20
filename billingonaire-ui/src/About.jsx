import React from 'react';
import { Container } from 'react-bootstrap';
import Header from './Header';

const About = () => (
  <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>
    <Header />
    <Container fluid className="flex-grow-1 d-flex flex-column p-0">
      <div className="text-column">
        <h1>About this app</h1>
        <p>
          This is a <a href="https://kit.svelte.dev">SvelteKit</a> app. You can make your own by typing the
          following into your command line and following the prompts:
        </p>
        <pre>npm create svelte@latest</pre>
        <p>
          The page you're looking at is purely static HTML, with no client-side interactivity needed.
          Because of that, we don't need to load any JavaScript. Try viewing the page's source, or opening
          the devtools network panel and reloading.
        </p>
        <p>
          The <a href="/sverdle">Sverdle</a> page illustrates SvelteKit's data loading and form handling. Try
          using it with JavaScript disabled!
        </p>
      </div>
    </Container>
    <footer className="bg-light text-center text-muted py-3 mt-auto border-top w-100">
      &copy; {new Date().getFullYear()} Billingonaire. All rights reserved.
    </footer>
  </div>
);

export default About;
