import React from 'react';
import { BrowserRouter as Router, Routes, Route } from 'react-router-dom';
import Layout from './Layout';
import Login from './Login';
import Upload from './Upload';
import Table from './Table';
import About from './About';

const App = () => (
  <Router>
    <Layout>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/upload" element={<Upload />} />
        <Route path="/table" element={<Table />} />
        <Route path="/about" element={<About />} />
        <Route path="*" element={<Login />} />
      </Routes>
    </Layout>
  </Router>
);

export default App;
