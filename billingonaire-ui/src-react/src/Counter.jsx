import React, { useState } from 'react';

const Counter = () => {
  const [count, setCount] = useState(0);

  return (
    <div className="counter">
      <button onClick={() => setCount(count - 1)} aria-label="Decrease the counter by one">
        <svg aria-hidden="true" viewBox="0 0 1 1">
          <path d="M0,0.5 L1,0.5" />
        </svg>
      </button>
      <div className="counter-viewport">
        <div className="counter-digits">
          <strong>{count}</strong>
        </div>
      </div>
      <button onClick={() => setCount(count + 1)} aria-label="Increase the counter by one">
        <svg aria-hidden="true" viewBox="0 0 1 1">
          <path d="M0,0.5 L1,0.5 M0.5,0 L0.5,1" />
        </svg>
      </button>
      <style>{`
        .counter { display: flex; border-top: 1px solid rgba(0,0,0,0.1); border-bottom: 1px solid rgba(0,0,0,0.1); margin: 1rem 0; }
        .counter button { width: 2em; padding: 0; display: flex; align-items: center; justify-content: center; border: 0; background-color: transparent; font-size: 2rem; }
        .counter button:hover { background-color: #f8f8f8; }
        .counter-viewport { width: 8em; height: 4em; overflow: hidden; text-align: center; position: relative; }
        .counter-digits { position: absolute; width: 100%; height: 100%; display: flex; align-items: center; justify-content: center; font-size: 4rem; color: #333; }
      `}</style>
    </div>
  );
};

export default Counter;
