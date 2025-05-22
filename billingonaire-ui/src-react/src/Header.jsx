import React from 'react';
import logo from './assets/react.svg'; // Replace with your logo path
// import github from '../lib/images/github.svg'; // Replace with your github icon path

const Header = () => (
  <header>
    <div className="corner">
      <a href="https://react.dev">
        <img src={logo} alt="React" />
      </a>
    </div>
    <nav>
      <ul>
        <li><a href="/about">About</a></li>
        <li><a href="/sverdle">Sverdle</a></li>
        <li><a href="/upload">Upload Board</a></li>
        <li><a href="/table">Search Board</a></li>
      </ul>
    </nav>
    <div className="corner">
      <a href="https://github.com/facebook/react">
        {/* <img src={github} alt="GitHub" /> */}
        <span>GitHub</span>
      </a>
    </div>
    <style>{`
      header { display: flex; justify-content: space-between; }
      .corner { width: 3em; height: 3em; }
      .corner a { display: flex; align-items: center; justify-content: center; width: 100%; height: 100%; }
      .corner img { width: 2em; height: 2em; object-fit: contain; }
      nav { display: flex; justify-content: center; }
      ul { display: flex; list-style: none; padding: 0; margin: 0; }
      li { margin: 0 1em; }
    `}</style>
  </header>
);

export default Header;
