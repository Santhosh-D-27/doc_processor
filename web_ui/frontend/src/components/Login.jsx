import React, { useState } from 'react';
import { motion } from 'framer-motion';
import { useNavigate } from 'react-router-dom';

const Login = () => {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [remember, setRemember] = useState(false);
  const [error, setError] = useState('');
  const navigate = useNavigate();

  const handleSubmit = (e) => {
    e.preventDefault();
    console.log('Login attempt:', { username, password }); // Debug log
    if (username === 'admin' && password === 'password123') {
      localStorage.setItem('authToken', 'sample-token');
      setError('');
      navigate('/dashboard');
    } else {
      setError('Invalid username or password. Please use "admin" and "password123".');
    }
  };

  const togglePassword = () => {
    setShowPassword(!showPassword);
  };

  return (
    <div className="min-h-screen flex items-center justify-center relative overflow-hidden bg-gradient-to-br from-slate-100 to-slate-300">
      <div className="absolute w-[400px] h-[300px] top-[-150px] left-[-100px] rotate-[-15deg] rounded-[50px] bg-white/20"></div>
      <div className="absolute w-[500px] h-[200px] bottom-[-100px] right-[-150px] rotate-[20deg] rounded-[40px] bg-white/15"></div>
      <div className="absolute w-[300px] h-[300px] top-1/2 left-[-50px] -translate-y-1/2 rotate-[-25deg] rounded-[30px] bg-white/12"></div>

      <motion.div
        className="glass-card-strong rounded-3xl shadow-modern-lg w-[900px] max-w-[90%] min-h-[550px] flex relative z-10"
        initial={{ opacity: 0, y: 30 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.6 }}
      >
        <div className="flex-1.2 bg-gradient-to-br from-indigo-900 via-indigo-800 to-indigo-950 relative overflow-hidden flex items-center justify-center p-10">
          <div className="absolute w-[200px] h-[150px] top-[-50px] right-[-50px] rotate-[-20deg] rounded-2xl bg-white/10"></div>
          <div className="absolute w-[150px] h-[200px] bottom-[-80px] left-[-30px] rotate-[25deg] rounded-2xl bg-white/15"></div>
          <div className="absolute w-[100px] h-[100px] top-1/2 left-[20%] -translate-y-1/2 rotate-[-45deg] rounded-2xl bg-white/10"></div>

          <div className="text-center text-white max-w-[320px] z-10">
            <motion.div
              className="w-[120px] h-[120px] bg-gradient-to-br from-white to-slate-100 rounded-3xl mx-auto mb-8 flex items-center justify-center shadow-[0_20px_40px_rgba(0,0,0,0.1),0_0_0_1px_rgba(255,255,255,0.1),inset_0_1px_0_rgba(255,255,255,0.2)] relative overflow-hidden"
              animate={{ y: [-10, 0, -10] }}
              transition={{ duration: 2, repeat: Infinity, ease: 'easeInOut' }}
            >
              <div className="absolute inset-0 bg-gradient-to-br from-transparent via-indigo-950/20 to-transparent rounded-3xl"></div>
              <span className="text-5xl bg-gradient-to-br from-indigo-900 to-indigo-700 bg-clip-text text-transparent">🚀</span>
            </motion.div>
            <motion.h1
              className="text-4xl font-bold mb-4 text-shadow-md"
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.2 }}
            >
              Welcome to
            </motion.h1>
            <motion.div
              className="text-2xl font-semibold mb-5 opacity-95"
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.3 }}
            >
              Dashboard
            </motion.div>
            <motion.p
              className="text-sm font-light leading-relaxed opacity-85"
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.4 }}
            >
              Document ingestion and classification
            </motion.p>
          </div>
        </div>

        <div className="flex-1 p-10 flex flex-col justify-center bg-gradient-to-br from-white to-blue-50">
          <form onSubmit={handleSubmit} className="login-form">
            <h1 className="text-3xl font-semibold text-slate-700 mb-10">Get started!</h1>

            <div className="mb-6">
              <label htmlFor="username" className="block mb-2 text-sm font-medium text-slate-600">
                User name
              </label>
              <div className="relative">
                <input
                  type="text"
                  id="username"
                  name="username"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  placeholder="Enter your user name or email"
                  required
                  className="w-full p-4 border-2 border-slate-200 rounded-xl text-sm text-slate-700 focus:outline-none focus:border-indigo-800 focus:ring-4 focus:ring-indigo-800/10 bg-white"
                />
                <span className="absolute right-4 top-1/2 -translate-y-1/2 text-slate-400 hover:text-indigo-800">👤</span>
              </div>
            </div>

            <div className="mb-6">
              <label htmlFor="password" className="block mb-2 text-sm font-medium text-slate-600">
                Password
              </label>
              <div className="relative">
                <input
                  type={showPassword ? 'text' : 'password'}
                  id="password"
                  name="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="Enter your password"
                  required
                  className="w-full p-4 border-2 border-slate-200 rounded-xl text-sm text-slate-700 focus:outline-none focus:border-indigo-800 focus:ring-4 focus:ring-indigo-800/10 bg-white"
                />
                <span
                  className="absolute right-4 top-1/2 -translate-y-1/2 text-slate-400 hover:text-indigo-800 cursor-pointer"
                  onClick={togglePassword}
                >
                  {showPassword ? '🙈' : '👁️'}
                </span>
              </div>
            </div>

            <div className="flex justify-between items-center mb-8">
              <div className="flex items-center">
                <input
                  type="checkbox"
                  id="remember"
                  name="remember"
                  checked={remember}
                  onChange={(e) => setRemember(e.target.checked)}
                  className="w-4 h-4 accent-indigo-800"
                />
                <label htmlFor="remember" className="ml-2 text-sm text-slate-600 cursor-pointer">
                  Remember me
                </label>
              </div>
              <a href="#" className="text-sm text-indigo-800 hover:underline font-medium">
                Forgot your password?
              </a>
            </div>

            {error && (
              <motion.div
                className="mb-4 text-red-500 text-sm font-medium"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ duration: 0.3 }}
              >
                {error}
              </motion.div>
            )}

            <motion.button
              type="submit"
              className="btn-modern w-full p-4 bg-gradient-to-r from-indigo-900 to-indigo-700 text-white rounded-xl font-semibold text-base shadow-modern hover:shadow-modern-lg hover:-translate-y-0.5 active:translate-y-0"
              whileHover={{ scale: 1.02 }}
              whileTap={{ scale: 0.98 }}
            >
              Login
            </motion.button>
          </form>
        </div>
      </motion.div>
    </div>
  );
};

export default Login;