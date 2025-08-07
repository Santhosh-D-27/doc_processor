import React, { useState, useEffect } from 'react';
import './Login.css';

const Login = () => {
    const [passwordVisible, setPasswordVisible] = useState(false);

    const togglePassword = () => {
        setPasswordVisible(!passwordVisible);
    };

    const handleSubmit = (e) => {
        e.preventDefault();
        alert('Login functionality would be implemented here!');
    };

    useEffect(() => {
        const container = document.querySelector('.container');
        container.style.opacity = '0';
        container.style.transform = 'translateY(30px)';

        setTimeout(() => {
            container.style.transition = 'all 0.6s ease';
            container.style.opacity = '1';
            container.style.transform = 'translateY(0)';
        }, 100);
    }, []);

    return (
        <div className="login-body">
            <div className="bg-shape shape-1"></div>
            <div className="bg-shape shape-2"></div>
            <div className="bg-shape shape-3"></div>

            <div className="container">
                <div className="left-panel">
                    <div className="left-shape left-shape-1"></div>
                    <div className="left-shape left-shape-2"></div>
                    <div className="left-shape left-shape-3"></div>
                    
                    <div className="welcome-content">
                        <div className="brand-logo">
                            <div className="logo-icon">🚀</div>
                        </div>
                        <h1>Welcome to</h1>
                        <div className="subtitle">Dashboard</div>
                        <p>Document ingestion and classification</p>
                    </div>
                </div>
                
                <div className="right-panel">
                    <form className="login-form" onSubmit={handleSubmit}>
                        <h1>Get started!</h1>
                        
                        <div className="form-group">
                            <label htmlFor="username">User name</label>
                            <div className="input-container">
                                <input type="text" id="username" name="username" placeholder="Enter your user name or email" required />
                                <span className="input-icon">👤</span>
                            </div>
                        </div>
                        
                        <div className="form-group">
                            <label htmlFor="password">Password</label>
                            <div className="input-container">
                                <input type={passwordVisible ? 'text' : 'password'} id="password" name="password" placeholder="Enter your password" required />
                                <span className="input-icon" onClick={togglePassword} id="toggleIcon">
                                    {passwordVisible ? '🙈' : '👁️'}
                                </span>
                            </div>
                        </div>
                        
                        <div className="form-options">
                            <div className="checkbox-group">
                                <input type="checkbox" id="remember" name="remember" />
                                <label htmlFor="remember">Remember me</label>
                            </div>
                            <a href="#" className="forgot-password">Forgot your password?</a>
                        </div>
                        
                        <button type="submit" className="login-btn">Login</button>
                    </form>
                </div>
            </div>
        </div>
    );
};

export default Login;
